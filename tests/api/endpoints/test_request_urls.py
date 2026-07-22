"""Tests for request-aware public URL derivation."""

import unittest
import urllib.parse
from unittest import mock

import fastapi

from imbi.api.endpoints import _request_urls


def _request(scheme: str, host: str, *, query: bytes = b'') -> fastapi.Request:
    return fastapi.Request(
        {
            'type': 'http',
            'method': 'GET',
            'scheme': scheme,
            'path': '/',
            'raw_path': b'/',
            'query_string': query,
            'headers': [(b'host', host.encode())],
            'server': (host, 443 if scheme == 'https' else 80),
            'client': ('127.0.0.1', 0),
        }
    )


def _cfg(public_base_url: str, cors: tuple[str, ...] = ()) -> mock.MagicMock:
    cfg = mock.MagicMock()
    cfg.public_base_url = public_base_url
    cfg.cors_allowed_origins = list(cors)
    cfg.api_prefix = urllib.parse.urlparse(public_base_url).path.rstrip('/')
    return cfg


class RequestUrlsTestCase(unittest.TestCase):
    def _patch_cfg(self, cfg: mock.MagicMock) -> None:
        patcher = mock.patch(
            'imbi.api.settings.get_server_config', return_value=cfg
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_public_base_url_origin_is_always_trusted(self) -> None:
        self._patch_cfg(_cfg('https://imbi.internal/api'))
        req = _request('https', 'imbi.internal')
        self.assertEqual(
            _request_urls.request_origin(req), 'https://imbi.internal'
        )

    def test_cors_origin_is_trusted(self) -> None:
        self._patch_cfg(
            _cfg('https://imbi.internal/api', ('https://imbi-public.test',))
        )
        req = _request('https', 'imbi-public.test')
        self.assertEqual(
            _request_urls.request_origin(req), 'https://imbi-public.test'
        )

    def test_untrusted_origin_returns_none(self) -> None:
        self._patch_cfg(_cfg('https://imbi.internal/api'))
        req = _request('https', 'evil.example')
        self.assertIsNone(_request_urls.request_origin(req))

    def test_scheme_must_match(self) -> None:
        """An http origin is not the same trusted origin as https."""
        self._patch_cfg(
            _cfg('https://imbi.internal/api', ('https://imbi-public.test',))
        )
        req = _request('http', 'imbi-public.test')
        self.assertIsNone(_request_urls.request_origin(req))

    def test_base_url_rebased_onto_trusted_origin(self) -> None:
        self._patch_cfg(
            _cfg('https://imbi.internal/api', ('https://imbi-public.test',))
        )
        req = _request('https', 'imbi-public.test')
        self.assertEqual(
            _request_urls.public_base_url_for_request(req),
            'https://imbi-public.test/api',
        )

    def test_base_url_falls_back_when_untrusted(self) -> None:
        self._patch_cfg(_cfg('https://imbi.internal/api'))
        req = _request('https', 'evil.example')
        self.assertEqual(
            _request_urls.public_base_url_for_request(req),
            'https://imbi.internal/api',
        )

    def test_base_url_preserves_empty_prefix(self) -> None:
        self._patch_cfg(
            _cfg('https://imbi.internal', ('https://imbi-public.test',))
        )
        req = _request('https', 'imbi-public.test')
        self.assertEqual(
            _request_urls.public_base_url_for_request(req),
            'https://imbi-public.test',
        )


if __name__ == '__main__':
    unittest.main()
