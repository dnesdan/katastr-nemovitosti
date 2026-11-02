import io
from http.client import HTTPResponse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

SKILL = Path(os.environ.get('KATASTR_SKILL_ROOT', str(Path(__file__).resolve().parents[1] / 'skills/katastr-nemovitosti')))
sys.path.insert(0, str(SKILL / 'scripts'))
from http_client import HttpClient, FetchError, AccessBlocked, CooldownError, FetchResult, validate_url, _PublicRedirect

URL = 'https://services.cuzk.gov.cz/test'

def public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]

class Response(io.BytesIO):
    def __init__(self, body=b'{"ok":true}', *, status=200, headers=None, url=URL):
        super().__init__(body)
        self.status = status
        self.headers = headers if headers is not None else {'Content-Length': str(len(body)), 'Content-Type': 'application/json'}
        self.url = url
    def geturl(self):
        return self.url

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
    def tearDown(self):
        self.temp.cleanup()
    def client(self, response=None, **kwargs):
        def transport(request, timeout):
            self.calls.append(request.full_url)
            return response() if callable(response) else Response()
        return HttpClient(cache_dir=self.temp.name, min_interval=0, resolver=public_dns, transport=transport, **kwargs)

    def test_cache_preserves_original_retrieval_time_and_avoids_second_request(self):
        c = self.client()
        a, b = c.fetch(URL), c.fetch(URL)
        self.assertFalse(a.from_cache)
        self.assertTrue(b.from_cache)
        self.assertEqual(a.retrieved_at, b.retrieved_at)
        self.assertEqual(len(self.calls), 1)

    def test_refresh_fetches_again(self):
        c = self.client()
        c.fetch(URL)
        self.assertFalse(c.fetch(URL, refresh=True).from_cache)
        self.assertEqual(len(self.calls), 2)

    def test_nonpublic_or_credential_url_is_rejected_before_network(self):
        bad = ['http://services.cuzk.gov.cz/', 'file:///etc/passwd', 'https://localhost/',
               'https://127.0.0.1/', 'https://[::1]/', 'https://u:p@services.cuzk.gov.cz/',
               'https://services.cuzk.gov.cz:8443/', 'https://services.cuzk.gov.cz/?ApiKey=hidden',
               'https://services.cuzk.gov.cz/\n', 'https://services.cuzk.gov.cz/a b',
               'https://nahlizenidokn.cuzk.gov.cz/', 'https://dpn.cuzk.gov.cz/']
        c = self.client()
        for url in bad:
            with self.subTest(url=url), self.assertRaises(FetchError): c.fetch(url)
        self.assertFalse(self.calls)

    def test_unknown_host_requires_explicit_allowlist(self):
        with self.assertRaises(FetchError): self.client().fetch('https://unknown.example/')
        self.assertFalse(self.calls)

    def test_dns_local_answer_stops_fetch(self):
        c = self.client()
        c.resolver = lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.2', 443))]
        with self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(self.calls)

    def test_mixed_public_private_dns_stops_fetch(self):
        c = self.client()
        c.resolver = lambda *a, **kw: public_dns() + [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443))]
        with self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(self.calls)

    def test_proxy_only_dns_fallback_is_limited_to_built_in_hosts(self):
        def no_dns(*args, **kwargs): raise socket.gaierror('proxy-only executor')
        c = self.client(); c.resolver = no_dns
        with patch('http_client.getproxies', return_value={'https':'http://proxy:8080'}):
            self.assertTrue(c.fetch(URL).json()['ok'])
            c.allowed_hosts = frozenset({'custom.example'})
            with self.assertRaises(FetchError): c.fetch('https://custom.example/')

    def test_without_proxy_dns_failure_remains_failure(self):
        c = self.client()
        def no_dns(*args, **kwargs): raise socket.gaierror('unavailable')
        c.resolver = no_dns
        with patch('http_client.getproxies', return_value={}), self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(self.calls)

    def test_cross_origin_redirect_is_rejected(self):
        handler = _PublicRedirect()
        with self.assertRaises(FetchError): handler.redirect_request(Request(URL), None, 302, '', {}, 'https://ags.cuzk.gov.cz/')
        with self.assertRaises(FetchError): handler.redirect_request(Request(URL), None, 302, '', {}, 'http://services.cuzk.gov.cz/')

    def test_same_origin_redirect_rechecks_destination(self):
        observed = []
        handler = _PublicRedirect(observed.append)
        redirected = handler.redirect_request(Request(URL), None, 302, '', {}, URL + '/canonical')
        self.assertEqual(observed, [URL + '/canonical'])
        self.assertEqual(redirected.full_url, URL + '/canonical')

    def test_cross_host_final_response_is_rejected(self):
        c = self.client(lambda:Response(url='https://ags.cuzk.gov.cz/test'))
        with self.assertRaises(FetchError): c.fetch(URL)

    def test_403_pauses_host_and_never_becomes_empty(self):
        c = self.client(lambda:Response(status=403))
        with self.assertRaises(AccessBlocked) as caught: c.fetch(URL)
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(CooldownError): c.fetch(URL + '?next=1')
        self.assertEqual(len(self.calls), 1)

    def test_429_httperror_pauses_host(self):
        def blocked(): raise HTTPError(URL, 429, 'rate limited', {'Retry-After':'120'}, None)
        c = self.client(blocked)
        with self.assertRaises(AccessBlocked): c.fetch(URL)
        with self.assertRaises(CooldownError): c.fetch(URL, refresh=True)

    def test_partial_content_is_not_success_or_cached(self):
        c = self.client(lambda:Response(status=206))
        with self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(list(Path(self.temp.name).glob('responses/*.json')))

    def test_truncated_body_is_not_cached(self):
        c = self.client(lambda:Response(b'{}', headers={'Content-Length':'100'}))
        with self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(list(Path(self.temp.name).glob('responses/*.json')))

    def test_byte_limit_with_and_without_length(self):
        for headers in ({'Content-Length':'20'}, {}):
            c = self.client(lambda:Response(b'x'*20,headers=headers), max_bytes=10)
            with self.assertRaises(FetchError): c.fetch(URL)
        self.assertFalse(list(Path(self.temp.name).glob('responses/*.json')))

    def test_invalid_length_and_compression_are_not_silent(self):
        for headers in ({'Content-Length':'n/a'}, {'Content-Encoding':'gzip'}):
            c = self.client(lambda:Response(headers=headers))
            with self.assertRaises(FetchError): c.fetch(URL)

    def test_corrupted_cache_is_refetched(self):
        c = self.client()
        c.fetch(URL)
        p = next(Path(self.temp.name).glob('responses/*.json'))
        value = json.loads(p.read_text()); value['body']='not base64';p.write_text(json.dumps(value))
        self.assertFalse(c.fetch(URL).from_cache)
        self.assertEqual(len(self.calls), 2)

    def test_cache_cannot_redirect_provenance(self):
        c = self.client(); c.fetch(URL)
        p = next(Path(self.temp.name).glob('responses/*.json'))
        value = json.loads(p.read_text());value['url']='https://ags.cuzk.gov.cz/wrong';p.write_text(json.dumps(value))
        self.assertFalse(c.fetch(URL).from_cache)

    def test_json_decode_failure_is_not_empty(self):
        r=FetchResult(b'<html>login</html>','text/html',URL,'2026-11-02T00:00:00+00:00')
        with self.assertRaises(FetchError): r.json()

    def test_nonfinite_json_and_invalid_limits_are_rejected(self):
        r=FetchResult(b'{"x":NaN}','application/json',URL,'2026-11-02T00:00:00+00:00')
        with self.assertRaises(FetchError):r.json()
        for values in ({'timeout':float('inf')},{'max_bytes':True},{'cache_ttl':float('nan')}):
            with self.assertRaises(ValueError):HttpClient(**values)

    def test_real_httpresponse_drip_body_stops_near_deadline(self):
        class SlowRaw(io.RawIOBase):
            def __init__(self, sock):
                self._sock = sock
                self.header = b'HTTP/1.1 200 OK\r\nContent-Length: 64\r\n\r\n'
                self.body = b'x' * 64
            def readable(self): return True
            def readinto(self, target):
                if self.header:
                    n = min(len(target),len(self.header));target[:n]=self.header[:n];self.header=self.header[n:];return n
                if not self.body: return 0
                delay = 0.005
                if self._sock.timeout < delay:
                    time.sleep(self._sock.timeout)
                    raise TimeoutError('remaining body budget elapsed')
                time.sleep(delay)
                target[:1]=self.body[:1];self.body=self.body[1:];return 1
        class FakeSocket:
            timeout = 1.0
            def __init__(self):self.timeouts=[]
            def settimeout(self,value):self.timeout=value;self.timeouts.append(value)
            def makefile(self,*args,**kwargs):return io.BufferedReader(SlowRaw(self))
        sock = FakeSocket();response = HTTPResponse(sock);response.begin()
        c = self.client(lambda:response,timeout=0.025)
        started = time.monotonic()
        with self.assertRaises(FetchError):c.fetch(URL)
        elapsed = time.monotonic()-started
        self.assertLess(elapsed,0.15)  # Old read(65536) took ~0.33 s.
        self.assertGreater(len(sock.timeouts),1)
        self.assertLess(sock.timeouts[-1],sock.timeouts[0])
        self.assertTrue(response.closed)
        self.assertFalse(list(Path(self.temp.name).glob('responses/*.json')))

    def test_url_normalization_removes_fragment_and_standard_port(self):
        self.assertEqual(validate_url('https://SERVICES.CUZK.GOV.CZ.:443/test#piece'), URL)

if __name__ == '__main__': unittest.main()
