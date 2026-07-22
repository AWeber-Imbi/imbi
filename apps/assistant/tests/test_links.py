"""Tests for the assistant links module."""

from unittest import mock

import httpx

from apps.assistant.tests import helpers
from imbi.assistant import links, settings


class FakeResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        return None


class LinksTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._assistant_settings = None
        links._url_patterns = None

    def tearDown(self) -> None:
        settings._assistant_settings = None
        links._url_patterns = None
        super().tearDown()

    async def test_no_ui_url_uses_fallback(self) -> None:
        with self.override_environment(IMBI_UI_URL=None):
            await links.initialize()
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())

    async def test_fetch_success(self) -> None:
        body = '- `/projects`: the project list.'
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient, 'get', return_value=FakeResponse(body)
            ),
        ):
            await links.initialize()
        self.assertEqual(body, links.get_url_patterns())

    async def test_internal_ui_url_preferred(self) -> None:
        body = '- `/projects`: the project list.'
        with (
            self.override_environment(
                IMBI_UI_URL='https://imbi.example.com',
                IMBI_INTERNAL_UI_URL='http://imbi-ui:5173',
            ),
            mock.patch.object(
                httpx.AsyncClient, 'get', return_value=FakeResponse(body)
            ) as mock_get,
        ):
            await links.initialize()
        self.assertEqual(body, links.get_url_patterns())
        mock_get.assert_called_once_with('http://imbi-ui:5173/llms.txt')

    async def test_public_ui_url_used_when_no_internal(self) -> None:
        body = '- `/projects`: the project list.'
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient, 'get', return_value=FakeResponse(body)
            ) as mock_get,
        ):
            await links.initialize()
        mock_get.assert_called_once_with('https://imbi.example.com/llms.txt')

    async def test_html_response_uses_fallback(self) -> None:
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient,
                'get',
                return_value=FakeResponse('<!DOCTYPE html><html></html>'),
            ),
        ):
            await links.initialize()
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())

    async def test_empty_response_uses_fallback(self) -> None:
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient,
                'get',
                return_value=FakeResponse('   '),
            ),
        ):
            await links.initialize()
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())

    async def test_invalid_url_uses_fallback(self) -> None:
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient,
                'get',
                side_effect=httpx.InvalidURL('bad url'),
            ),
        ):
            await links.initialize()
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())

    async def test_fetch_error_uses_fallback(self) -> None:
        with (
            self.override_environment(IMBI_UI_URL='https://imbi.example.com'),
            mock.patch.object(
                httpx.AsyncClient,
                'get',
                side_effect=httpx.ConnectError('boom'),
            ),
        ):
            await links.initialize()
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())

    def test_get_url_patterns_default(self) -> None:
        links._url_patterns = None
        self.assertEqual(links.FALLBACK_URL_PATTERNS, links.get_url_patterns())
