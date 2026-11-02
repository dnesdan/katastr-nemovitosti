#!/usr/bin/env python3
"""Bounded, read-only public HTTP client for Katastr a souvislosti.

Only successful complete responses are cached. The cache and host gate are shared
by processes. OS locks are never deleted to recover a lock:
the operating system releases them when the owning process exits.

Adapted from dnesdan/pamet-krajiny (MIT), with exact-host policy, DNS checks,
HTTPS-only transport and explicit exclusions for interactive cadastral portals.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from http.client import HTTPException
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.request import Request, build_opener, getproxies, HTTPRedirectHandler


class FetchError(RuntimeError):
    """A request was not completed; do not treat it as absence of a record."""


class AccessBlocked(FetchError):
    def __init__(self, status: int, url: str):
        self.status, self.url = status, url
        super().__init__(f"HTTP {status} for {url}; stop, check access conditions; no automatic retry.")


class CooldownError(FetchError):
    """The host gate is busy or its cooldown has not elapsed."""


DEFAULT_HOSTS = frozenset({
    "ags.cuzk.gov.cz", "ags.cuzk.cz", "services.cuzk.gov.cz", "services.cuzk.cz",
    "geoportal.cuzk.gov.cz", "geoportal.cuzk.cz", "heis.vuv.cz", "ags.cenia.cz",
    "gis.nature.cz", "aopkcr.maps.arcgis.com", "mapy.geology.cz", "mapy.geology.gov.cz",
    "mapy.nature.cz", "geoportal.npu.cz", "gis.npu.cz", "gis.cenia.cz",
})
INTERACTIVE_HOSTS = frozenset({"nahlizenidokn.cuzk.gov.cz", "nahlizenidokn.cuzk.cz", "dpn.cuzk.gov.cz"})
SECRET_PARAMETERS = frozenset({"apikey", "api_key", "api-key", "key", "access_token", "token", "authorization", "password", "secret", "credential"})


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    content_type: str
    url: str
    retrieved_at: str
    from_cache: bool = False

    def json(self) -> Any:
        try:
            def reject_constant(value):
                raise ValueError("Non-finite JSON number")
            return json.loads(self.data.decode("utf-8-sig"), parse_constant=reject_constant)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise FetchError(f"Response from {self.url} is not UTF-8 JSON") from exc


def validate_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 12000 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise FetchError("URL must be text without control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchError("Malformed public source URL") from exc
    if parts.scheme != "https" or not parts.hostname:
        raise FetchError("Only absolute HTTPS URLs are supported")
    if parts.username or parts.password:
        raise FetchError("Do not place credentials in a source URL")
    if port not in (None, 443):
        raise FetchError("Public source clients use HTTPS port 443 only")
    try:
        host = parts.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise FetchError("Malformed public source hostname") from exc
    if host in INTERACTIVE_HOSTS:
        raise FetchError("This interactive cadastral portal must be used manually; automated fetching is not supported")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise FetchError("Local destinations are not public research sources")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise FetchError("Private or special-use IP addresses are not public research sources")
    if any(key.casefold() in SECRET_PARAMETERS for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise FetchError("Credentials in URL parameters are not supported by this public client")
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise FetchError("Use a public DNS hostname, not an IP literal or unusual host syntax")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


class _PublicRedirect(HTTPRedirectHandler):
    def __init__(self, destination_check=None):
        self.destination_check = destination_check

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        clean = validate_url(newurl)
        if urlsplit(clean).hostname != urlsplit(req.full_url).hostname:
            raise FetchError("Cross-host redirect: inspect the destination and request its canonical public URL separately")
        if self.destination_check:
            self.destination_check(clean)
        return super().redirect_request(req, fp, code, msg, headers, clean)


@contextmanager
def _lock(path: Path):
    """Nonblocking process lock; lock files persist, so there is no inode race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise CooldownError("Another process is already using this host; try later") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CooldownError("Another process is already using this host; try later") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _set_remaining_timeout(response, remaining: float) -> None:
    """Tighten the urllib HTTPResponse socket timeout before each buffer read.

    The standard response owns fp -> raw -> _sock. Traverse only these known
    transport attributes; in-memory/custom test transports may have no socket.
    No helper thread or additional connection is created.
    """
    pending, seen = [response], set()
    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        setter = getattr(item, "settimeout", None)
        if callable(setter):
            setter(remaining)
            return
        for name in ("fp", "raw", "_sock"):
            child = getattr(item, name, None)
            if child is not None:
                pending.append(child)


class HttpClient:
    def __init__(self, cache_dir=None, timeout=25, max_bytes=8_000_000,
                 min_interval=1.0, cache_ttl=86400,
                 user_agent="KatastrASouvislosti/0.1 (+https://github.com/dnesdan/katastr-nemovitosti)",
                 transport=None, allowed_hosts=None, resolver=None):
        durations = (timeout, min_interval, cache_ttl)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in durations) or not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or timeout <= 0 or max_bytes <= 0 or min_interval < 0 or cache_ttl < 0:
            raise ValueError("Invalid HTTP limits")
        default = Path(tempfile.gettempdir()) / ("katastr-zdroje-" + str(getattr(os, "getuid", lambda: "user")()))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default
        self.timeout, self.max_bytes = timeout, max_bytes
        self.min_interval, self.cache_ttl = min_interval, cache_ttl
        self.user_agent = user_agent
        self.allowed_hosts = frozenset(allowed_hosts) if allowed_hosts is not None else DEFAULT_HOSTS
        self.resolver = resolver or socket.getaddrinfo
        # build_opener keeps environment proxy handling and default TLS verification.
        opener = build_opener(_PublicRedirect(self._check_destination))
        self.transport = transport or (lambda request, timeout: opener.open(request, timeout=timeout))

    def _check_destination(self, url: str) -> None:
        host = urlsplit(validate_url(url)).hostname
        if host not in self.allowed_hosts:
            raise FetchError("Host is not in the public source allowlist; inspect the source and explicitly configure its exact hostname")
        try:
            addresses = self.resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            # Managed executors can delegate all destination DNS to the inherited
            # HTTPS proxy. Only the built-in fixed official hosts may use that
            # route; arbitrary extra hostnames still need local public resolution.
            # TLS verification and the environment's egress policy stay enabled.
            if host in DEFAULT_HOSTS and getproxies().get("https"):
                return
            raise FetchError("Public source DNS resolution failed; no absence of records can be inferred") from exc
        if not addresses:
            raise FetchError("Public source DNS returned no address")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address[4][0])
            except (ValueError, IndexError, TypeError) as exc:
                raise FetchError("Unexpected DNS result") from exc
            if not ip.is_global:
                raise FetchError("Source resolves to a private or special-use address")

    def _cached(self, path: Path, url: str) -> FetchResult | None:
        cached = _read_json(path)
        try:
            age = time.time() - cached["saved_at"]
            if cached["request_url"] != url or age < 0 or age > self.cache_ttl:
                return None
            body = base64.b64decode(cached["body"], validate=True)
            if len(body) > self.max_bytes or hashlib.sha256(body).hexdigest() != cached["sha256"]:
                return None
            final = validate_url(cached["url"])
            if urlsplit(final).hostname != urlsplit(url).hostname:
                return None
            return FetchResult(body, cached["content_type"], cached["url"], cached["retrieved_at"], True)
        except (KeyError, ValueError, TypeError, FetchError):
            return None

    def _blocked(self, state_path: Path, state: dict, status: int, headers, url: str):
        wait = 3600 if status in (401, 403) else 60
        retry = headers.get("Retry-After", "") if headers else ""
        if retry:
            try:
                wait = max(wait, int(retry))
            except ValueError:
                try:
                    wait = max(wait, parsedate_to_datetime(retry).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    pass
        state["blocked_until"] = time.time() + max(1, min(wait, 86400))
        state["last_status"] = status
        _atomic_json(state_path, state)
        raise AccessBlocked(status, url)

    def fetch(self, url: str, refresh: bool = False) -> FetchResult:
        url = validate_url(url)
        if urlsplit(url).hostname not in self.allowed_hosts:
            raise FetchError("Host is not in the public source allowlist")
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        host = (urlsplit(url).hostname or "").lower()
        host_key = hashlib.sha256(host.encode("ascii", "ignore")).hexdigest()
        cache_path = self.cache_dir / "responses" / (key + ".json")
        state_path = self.cache_dir / "hosts" / (host_key + ".json")
        if not refresh:
            hit = self._cached(cache_path, url)
            if hit:
                return hit
        with _lock(self.cache_dir / "hosts" / (host_key + ".lock")):
            # Recheck after locking: a competing process may have completed the URL.
            if not refresh:
                hit = self._cached(cache_path, url)
                if hit:
                    return hit
            state = _read_json(state_path)
            now = time.time()
            remaining = float(state.get("blocked_until", 0)) - now
            if remaining > 0:
                raise CooldownError(f"Host is paused after HTTP {state.get('last_status', 'error')}; retry in about {int(remaining) + 1} s")
            pause = float(state.get("last_request", 0)) + self.min_interval - now
            if pause > 2:
                raise CooldownError(f"Respect the host interval; retry in about {int(pause) + 1} s")
            if pause > 0:
                time.sleep(pause)
            state["last_request"] = time.time()
            _atomic_json(state_path, state)
            request = Request(url, headers={"User-Agent": self.user_agent,
                                           "Accept": "application/json, application/xml, text/xml, */*;q=0.5"})
            self._check_destination(url)
            started = time.monotonic()
            try:
                with self.transport(request, self.timeout) as response:
                    status = getattr(response, "status", 200)
                    if status in (401, 403, 429, 503):
                        self._blocked(state_path, state, status, response.headers, url)
                    if status != 200:
                        raise FetchError(f"HTTP {status} for {url}; no record absence can be inferred")
                    length = response.headers.get("Content-Length")
                    expected_length = None
                    if length:
                        try:
                            expected_length = int(length)
                            if expected_length < 0:
                                raise FetchError("Invalid negative Content-Length")
                            if expected_length > self.max_bytes:
                                raise FetchError(f"Response exceeds {self.max_bytes} byte limit")
                        except ValueError as exc:
                            raise FetchError("Invalid Content-Length") from exc
                    encoding = response.headers.get("Content-Encoding", "identity").lower()
                    if encoding not in ("", "identity"):
                        raise FetchError("Compressed HTTP payload is not supported; request an identity response")
                    chunks, size = [], 0
                    deadline = started + self.timeout
                    reader = getattr(response, "read1", None)
                    single_buffer = callable(reader)
                    if not single_buffer:
                        # Minimal custom responses can only expose read(). A
                        # single byte avoids its fill-the-whole-buffer loop.
                        reader = response.read
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise FetchError("Response exceeded the body read deadline")
                        _set_remaining_timeout(response, remaining)
                        part = reader(min(65536 if single_buffer else 1, self.max_bytes + 1 - size))
                        if time.monotonic() >= deadline:
                            raise FetchError("Response exceeded the total read deadline")
                        if not part:
                            break
                        chunks.append(part)
                        size += len(part)
                        if size > self.max_bytes:
                            raise FetchError(f"Response exceeds {self.max_bytes} byte limit")
                    body = b"".join(chunks)
                    if expected_length is not None and len(body) != expected_length:
                        raise FetchError("Incomplete response: body length differs from Content-Length")
                    final_url = validate_url(response.geturl())
                    if urlsplit(final_url).hostname != urlsplit(url).hostname:
                        raise FetchError("Unexpected cross-host response; inspect its canonical URL")
                    content_type = response.headers.get("Content-Type", "application/octet-stream")
            except HTTPError as exc:
                if exc.code in (401, 403, 429, 503):
                    self._blocked(state_path, state, exc.code, exc.headers, url)
                raise FetchError(f"HTTP {exc.code} for {url}; no record absence can be inferred") from exc
            except (URLError, OSError, TimeoutError, HTTPException) as exc:
                raise FetchError(f"Request failed for {url}: {exc}") from exc
            retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _atomic_json(cache_path, {
                "request_url": url, "url": final_url, "retrieved_at": retrieved,
                "saved_at": time.time(), "content_type": content_type,
                "sha256": hashlib.sha256(body).hexdigest(), "body": base64.b64encode(body).decode("ascii")})
            return FetchResult(body, content_type, final_url, retrieved, False)
