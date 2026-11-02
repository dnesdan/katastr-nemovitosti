"""Versioned, evidence-first property cases. Python 3.10+, standard library only."""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

VERSION = "property-case/1.0"
STATUSES = {"supported", "conflict", "missing", "not_covered", "unverified"}
COLLECTIONS = ("objects", "sources", "documents", "evidence", "findings", "rights", "next_documents", "research_log")
FIELDS = {
    "case": {"id", "title", "purpose", "locality", "region", "created_at", "as_of", "mode", "summary", "scope_note", "sharing"},
    "objects": {"id", "type", "label", "cadastral_area", "parcel", "registry_id", "address", "geometry", "geometry_note", "source_ids"},
    "sources": {"id", "title", "url", "provider", "accessed_at", "data_date", "scope", "access", "public"},
    "documents": {"id", "title", "kind", "sha256", "pages", "register_state_at", "issued_at", "imported_at", "completeness", "seal_status", "public", "inspection"},
    "evidence": {"id", "source_id", "document_id", "locator", "quote", "observed_at", "public"},
    "findings": {"id", "title", "topic", "status", "severity", "summary", "object_ids", "evidence_ids", "next_step", "public"},
    "rights": {"id", "type", "beneficiary_object_ids", "burdened_object_ids", "share", "description", "evidence_ids", "public"},
    "next_documents": {"id", "title", "reason", "source_url", "for_finding", "priority", "status", "public"},
    "research_log": {"at", "source_id", "query", "status", "note"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_case(title: str, locality: str, purpose: str = "Orientace v nemovitosti", region: str = "") -> dict:
    if not all(isinstance(v, str) for v in (title, locality, purpose, region)):
        raise ValueError("Název, lokalita, účel a kraj musí být text.")
    if not title.strip() or not locality.strip() or not purpose.strip():
        raise ValueError("Vyplň název případu a lokalitu; parcelu určuj i katastrálním územím.")
    now = utc_now()
    case = {"schema_version": VERSION, "case": {
        "id": "pripad-" + uuid4().hex[:12], "title": title.strip(), "purpose": purpose.strip(), "locality": locality.strip(),
        "region": region, "created_at": now, "as_of": now[:10], "mode": "research", "summary": "",
        "scope_note": "Případ založen. Identita nemovitosti a dostupnost podkladů dosud nejsou ověřeny.",
        "sharing": "private",
    }}
    case.update({name: [] for name in COLLECTIONS})
    return case


def safe_url(value: object) -> bool:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value) or any(c in value for c in ("<", ">", '"', "\\")):
        return False
    try:
        value.encode("utf-8")
        parsed = urlsplit(value)
        _ = parsed.port
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except (ValueError, UnicodeError):
        return False


def _date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2}))?", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _finite(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _json_problem(value) -> str | None:
    """Reject non-JSON, cyclic, nonfinite or excessively deep programmatic input."""
    active = set()
    count = 0
    def visit(item, depth):
        nonlocal count
        count += 1
        if depth > 64 or count > 200000:
            return "JSON případu je příliš hluboký nebo rozsáhlý."
        if item is None or isinstance(item, bool):
            return None
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError:
                return "Text obsahuje neplatný Unicode znak."
            return None
        if isinstance(item, int):
            return "Číslo přesahuje podporovaný rozsah." if item.bit_length() > 1024 else None
        if isinstance(item, float):
            return None if math.isfinite(item) else "JSON nesmí obsahovat NaN ani nekonečno."
        if not isinstance(item, (list, dict)):
            return "Případ obsahuje hodnotu mimo datové typy JSON."
        if id(item) in active:
            return "JSON případ nesmí obsahovat cyklické odkazy."
        active.add(id(item))
        try:
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        return "Klíče JSON objektů musí být text."
                    issue = visit(key, depth+1) or visit(child, depth+1)
                    if issue:
                        return issue
            else:
                for child in item:
                    issue = visit(child, depth+1)
                    if issue:
                        return issue
        finally:
            active.remove(id(item))
        return None
    return visit(value, 0)


def geometry_errors(geometry: object) -> list[str]:
    if geometry is None:
        return []
    if not isinstance(geometry, dict) or set(geometry) != {"type", "coordinates"}:
        return ["Geometrie musí být GeoJSON type/coordinates v EPSG:4326."]
    errors = []
    kind, coords = geometry["type"], geometry["coordinates"]

    def point(p):
        ok = isinstance(p, list) and len(p) == 2 and all(_finite(v) for v in p)
        if not ok or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90):
            errors.append("Souřadnice vyžadují konečné [longitude, latitude] v EPSG:4326.")

    def line(line_coords, ring=False):
        if not isinstance(line_coords, list) or len(line_coords) < (4 if ring else 2):
            errors.append("Neúplná linie nebo polygonový prstenec.")
            return
        for p in line_coords:
            point(p)
        if ring and line_coords[0] != line_coords[-1]:
            errors.append("Polygonový prstenec není uzavřený.")

    def polygon(poly):
        if not isinstance(poly, list) or not poly:
            errors.append("Polygon musí obsahovat alespoň jeden prstenec.")
            return
        for ring in poly:
            line(ring, True)

    if kind == "Point":
        point(coords)
    elif kind == "MultiPoint":
        if not isinstance(coords, list) or not coords:
            errors.append("MultiPoint je prázdný.")
        else:
            for p in coords:
                point(p)
    elif kind == "LineString":
        line(coords)
    elif kind == "MultiLineString":
        if not isinstance(coords, list) or not coords:
            errors.append("MultiLineString je prázdný.")
        else:
            for part in coords:
                line(part)
    elif kind == "Polygon":
        polygon(coords)
    elif kind == "MultiPolygon":
        if not isinstance(coords, list) or not coords:
            errors.append("MultiPolygon je prázdný.")
        else:
            for poly in coords:
                polygon(poly)
    else:
        errors.append("Podporované geometrie: Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon.")
    return errors


def validate_case(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Kořen případu musí být JSON objekt."]
    problem = _json_problem(data)
    if problem:
        return [problem]
    expected = {"schema_version", "case", *COLLECTIONS}
    if set(data) != expected:
        errors.append(f"Nesprávné kořenové položky: chybí {sorted(expected-set(data))}, navíc {sorted(set(data)-expected)}.")
    if data.get("schema_version") != VERSION:
        errors.append(f"Vyžadována verze {VERSION}.")
    meta = data.get("case")
    if not isinstance(meta, dict):
        errors.append("case musí být objekt.")
        meta = {}

    def unknown(row, fields, context):
        if set(row) - fields:
            errors.append(f"{context}: neznámé položky {sorted(set(row)-fields)}.")

    def string(row, key, context, required=False):
        if key not in row:
            if required:
                errors.append(f"{context}: chybí {key}.")
        elif not isinstance(row[key], str) or (required and not row[key].strip()):
            errors.append(f"{context}: {key} musí být {'neprázdný ' if required else ''}text.")

    def enum(row, key, values, context):
        if not isinstance(row.get(key), str) or row[key] not in values:
            errors.append(f"{context}: nepřípustná hodnota {key}.")

    unknown(meta, FIELDS["case"], "case")
    for key in FIELDS["case"]:
        string(meta, key, "case", required=key in {"id", "title", "purpose", "locality", "created_at", "as_of", "mode", "sharing"})
    if isinstance(meta.get("id"), str) and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", meta["id"]):
        errors.append("case: id musí být krátký identifikátor bez mezer.")
    enum(meta, "mode", {"synthetic", "research"}, "case")
    enum(meta, "sharing", {"private", "public-reviewed"}, "case")
    for field in ("created_at", "as_of"):
        if not _date(meta.get(field)):
            errors.append(f"case: {field} musí být ISO datum nebo čas.")

    rows: dict[str, list[dict]] = {}
    ids: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for collection in COLLECTIONS:
        value = data.get(collection)
        if not isinstance(value, list):
            errors.append(f"{collection} musí být pole.")
            value = []
        rows[collection] = []
        ids[collection] = set()
        for n, row in enumerate(value):
            where = f"{collection}[{n}]"
            if not isinstance(row, dict):
                errors.append(f"{where}: vyžadován objekt.")
                continue
            rows[collection].append(row)
            unknown(row, FIELDS[collection], where)
            if collection != "research_log":
                identifier = row.get("id")
                if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", identifier):
                    errors.append(f"{where}: id musí být krátký identifikátor bez mezer.")
                elif identifier in all_ids:
                    errors.append(f"{where}: duplicitní id {identifier}.")
                else:
                    ids[collection].add(identifier)
                    all_ids.add(identifier)
            if "public" in row and not isinstance(row["public"], bool):
                errors.append(f"{where}: public musí být boolean.")

    def refs(row, key, target, context, required=False):
        value = row.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            errors.append(f"{context}: {key} musí být pole ID.")
            return
        if required and not value:
            errors.append(f"{context}: závěr vyžaduje konkrétní důkaz.")
        if len(set(value)) != len(value):
            errors.append(f"{context}: duplicitní vazba v {key}.")
        for identifier in value:
            if identifier not in ids[target]:
                errors.append(f"{context}: neexistující {key}={identifier}.")

    parcel_identities = set()
    for row in rows["objects"]:
        where = f"objects/{row.get('id')}"
        enum(row, "type", {"parcel", "building", "unit", "address", "area"}, where)
        string(row, "label", where, True)
        for field in ("address", "registry_id", "geometry_note"):
            string(row, field, where)
        if "cadastral_area" in row:
            area = row["cadastral_area"]
            if not isinstance(area, dict) or set(area)-{"code", "name"}:
                errors.append(f"{where}: nesprávné cadastral_area.")
            else:
                if "code" in area and (not isinstance(area["code"], str) or not re.fullmatch(r"[0-9]{6}", area["code"])):
                    errors.append(f"{where}: kód katastrálního území musí mít šest číslic.")
                string(area, "name", where)
        if "parcel" in row:
            parcel = row["parcel"]
            if not isinstance(parcel, dict) or set(parcel) != {"number", "series"}:
                errors.append(f"{where}: parcela vyžaduje number a series.")
            else:
                if not isinstance(parcel["number"], str) or not re.fullmatch(r"[1-9][0-9]*(?:/[1-9][0-9]*)?", parcel["number"]):
                    errors.append(f"{where}: nesprávné parcelní číslo.")
                enum(parcel, "series", {"land", "building"}, where)
        if row.get("type") == "parcel" and ("parcel" not in row or not isinstance(row.get("cadastral_area"), dict) or not row["cadastral_area"].get("code")):
            errors.append(f"{where}: parcelu určují kód katastru, číslo a číselná řada.")
        if row.get("type") == "parcel" and isinstance(row.get("cadastral_area"), dict) and isinstance(row.get("parcel"), dict):
            identity = (row["cadastral_area"].get("code"), row["parcel"].get("series"), row["parcel"].get("number"))
            if all(isinstance(value, str) and value for value in identity):
                if identity in parcel_identities:
                    errors.append(f"{where}: duplicitní parcelní identita v témže katastru a číselné řadě.")
                parcel_identities.add(identity)
        refs(row, "source_ids", "sources", where)
        errors.extend(f"{where}: {e}" for e in geometry_errors(row.get("geometry")))
        if row.get("geometry") is not None and (not isinstance(row.get("geometry_note"), str) or not row["geometry_note"].strip()):
            errors.append(f"{where}: geometrie vyžaduje původ/přesnost v geometry_note.")

    for row in rows["sources"]:
        where = f"sources/{row.get('id')}"
        for field in ("title", "provider", "scope"):
            string(row, field, where, True)
        enum(row, "access", {"public", "user_document"}, where)
        if row.get("access") == "public" and not safe_url(row.get("url")):
            errors.append(f"{where}: veřejný zdroj vyžaduje bezpečné HTTP(S) URL.")
        if "url" in row and not safe_url(row["url"]):
            errors.append(f"{where}: nepřípustné URL.")
        for key in ("accessed_at", "data_date"):
            if key in row and row[key] is not None and row[key] != "" and not _date(row[key]):
                errors.append(f"{where}: {key} není ISO datum/čas.")
        if not _date(row.get("accessed_at")):
            errors.append(f"{where}: chybí čas přístupu ke zdroji.")

    for row in rows["documents"]:
        where = f"documents/{row.get('id')}"
        string(row, "title", where, True)
        string(row, "kind", where, True)
        if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]):
            errors.append(f"{where}: vyžadován SHA256 originálu.")
        pages = row.get("pages")
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
            errors.append(f"{where}: pages musí být nezáporné celé číslo.")
        enum(row, "completeness", {"complete", "partial", "unknown"}, where)
        enum(row, "seal_status", {"not_checked", "present_unverified", "verified", "invalid"}, where)
        for key in ("register_state_at", "issued_at", "imported_at"):
            if key in row and row[key] is not None and row[key] != "" and not _date(row[key]):
                errors.append(f"{where}: {key} není ISO datum/čas.")
        if "inspection" in row and not isinstance(row["inspection"], dict):
            errors.append(f"{where}: inspection musí být objekt.")

    for row in rows["evidence"]:
        where = f"evidence/{row.get('id')}"
        targets = [name for name in ("source_id", "document_id") if name in row]
        if len(targets) != 1:
            errors.append(f"{where}: důkaz vyžaduje právě jeden source_id nebo document_id.")
        else:
            target = targets[0]
            if not isinstance(row[target], str) or row[target] not in ids["sources" if target == "source_id" else "documents"]:
                errors.append(f"{where}: neexistující zdroj důkazu.")
        locator = row.get("locator")
        if not isinstance(locator, dict) or not locator:
            errors.append(f"{where}: chybí konkrétní lokátor.")
        else:
            unknown(locator, {"page", "section", "attachment", "bbox", "note"}, where)
            if "page" in locator and (not isinstance(locator["page"], int) or isinstance(locator["page"], bool) or locator["page"] < 1):
                errors.append(f"{where}: stránky se číslují od 1.")
            for key in ("section", "attachment", "note"):
                string(locator, key, where)
            if not (locator.get("page") or any(isinstance(locator.get(k), str) and locator[k].strip() for k in ("section", "attachment", "note"))):
                errors.append(f"{where}: lokátor musí vysvětlit, kde byl údaj nalezen.")
            if "bbox" in locator and (not isinstance(locator["bbox"], list) or len(locator["bbox"]) != 4 or not all(_finite(v) for v in locator["bbox"])):
                errors.append(f"{where}: bbox musí obsahovat čtyři konečná čísla.")
            elif "bbox" in locator and (locator["bbox"][0] >= locator["bbox"][2] or locator["bbox"][1] >= locator["bbox"][3]):
                errors.append(f"{where}: bbox musí mít kladnou šířku a výšku.")
            page = locator.get("page")
            document = next((d for d in rows["documents"] if d.get("id") == row.get("document_id")), None)
            if document and isinstance(page, int) and not isinstance(page, bool) and not locator.get("attachment"):
                pages = document.get("pages")
                if isinstance(pages, int) and not isinstance(pages, bool) and page > pages:
                    errors.append(f"{where}: citovaná stránka přesahuje počet stran dokumentu.")
        string(row, "quote", where)
        if "observed_at" in row and row["observed_at"] is not None and row["observed_at"] != "" and not _date(row["observed_at"]):
            errors.append(f"{where}: observed_at není ISO datum/čas.")

    for row in rows["findings"]:
        where = f"findings/{row.get('id')}"
        for key in ("title", "topic", "summary"):
            string(row, key, where, True)
        string(row, "next_step", where)
        enum(row, "status", STATUSES, where)
        enum(row, "severity", {"high", "medium", "info"}, where)
        refs(row, "object_ids", "objects", where)
        refs(row, "evidence_ids", "evidence", where, row.get("status") in ("supported", "conflict"))

    for row in rows["rights"]:
        where = f"rights/{row.get('id')}"
        string(row, "type", where, True)
        string(row, "description", where, True)
        for key in ("beneficiary_object_ids", "burdened_object_ids"):
            refs(row, key, "objects", where)
        refs(row, "evidence_ids", "evidence", where, True)
        if "share" in row:
            share = row["share"]
            if not isinstance(share, dict) or set(share) != {"numerator", "denominator"} or not all(isinstance(v,int) and not isinstance(v,bool) for v in share.values()) or not 0 < share["numerator"] <= share["denominator"]:
                errors.append(f"{where}: podíl musí být přesný kladný zlomek nejvýše 1.")

    for row in rows["next_documents"]:
        where = f"next_documents/{row.get('id')}"
        for key in ("title", "reason"):
            string(row, key, where, True)
        enum(row, "priority", {"high", "medium", "info"}, where)
        enum(row, "status", {"needed", "received"}, where)
        if not isinstance(row.get("for_finding"), str) or row["for_finding"] not in ids["findings"]:
            errors.append(f"{where}: požadavek musí odkazovat na existující otázku/nález.")
        if "source_url" in row and row["source_url"] != "" and not safe_url(row["source_url"]):
            errors.append(f"{where}: nepřípustné URL.")

    for row in rows["research_log"]:
        where = "research_log"
        enum(row, "status", {"ok", "empty", "blocked", "error", "planned"}, where)
        if not _date(row.get("at")):
            errors.append("research_log: at musí být ISO datum/čas.")
        for key in ("query", "note"):
            string(row, key, where, True)
        if "source_id" in row and (not isinstance(row["source_id"], str) or row["source_id"] not in ids["sources"]):
            errors.append("research_log: neexistující source_id.")
    return errors


def require_valid(data: object) -> dict:
    errors = validate_case(data)
    if errors:
        raise ValueError("\n".join(errors))
    return data


def read_case(path: Path | str) -> dict:
    p = Path(path)
    if p.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Případ přesahuje limit 20 MiB; originální dokumenty ukládej samostatně.")

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicitní JSON klíč: {key}")
            out[key] = value
        return out

    def bad_constant(value):
        raise ValueError(f"Neplatné JSON číslo: {value}")

    return require_valid(json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=bad_constant))


def public_case(data: dict) -> dict:
    """Explicit reviewed subset, not automatic personal-data anonymisation."""
    require_valid(data)
    if data["case"]["sharing"] != "public-reviewed":
        raise ValueError("Před veřejným exportem zkontroluj všechny texty a nastav case.sharing na public-reviewed.")
    out = copy.deepcopy(data)
    for name in ("sources", "documents", "evidence", "findings", "rights", "next_documents"):
        out[name] = [r for r in out[name] if r.get("public") is True]
    # Original text, paths, attachments and extraction internals are never exported.
    for doc in out["documents"]:
        doc.pop("inspection", None)
    source_ids = {r["id"] for r in out["sources"]}
    doc_ids = {r["id"] for r in out["documents"]}
    out["evidence"] = [r for r in out["evidence"] if r.get("source_id") in source_ids or r.get("document_id") in doc_ids]
    evidence_ids = {r["id"] for r in out["evidence"]}
    for name in ("findings", "rights"):
        out[name] = [r for r in out[name] if set(r.get("evidence_ids", [])) <= evidence_ids]
    finding_ids = {r["id"] for r in out["findings"]}
    out["next_documents"] = [r for r in out["next_documents"] if r["for_finding"] in finding_ids]
    for obj in out["objects"]:
        obj["source_ids"] = [i for i in obj.get("source_ids", []) if i in source_ids]
    out["research_log"] = []
    return require_valid(out)


def compare_cases(older: dict, newer: dict) -> dict:
    """Compare recorded observations, without inferring registry transactions."""
    require_valid(older)
    require_valid(newer)
    if older["case"]["id"] != newer["case"]["id"]:
        raise ValueError("Porovnávat lze pouze časové stavy stejného case.id.")
    changes = {}
    for name in ("objects", "sources", "documents", "evidence", "findings", "rights", "next_documents"):
        a, b = ({r["id"]:r for r in c[name]} for c in (older, newer))
        changes[name] = {"added": sorted(b.keys()-a.keys()), "removed": sorted(a.keys()-b.keys()), "changed": sorted(k for k in a.keys()&b.keys() if a[k] != b[k])}
    return {"case_id": newer["case"]["id"], "from": older["case"]["as_of"], "to": newer["case"]["as_of"],
            "note": "Srovnání uložených podkladů; neprokazuje samo o sobě změnu práv v katastru.", "changes": changes}
