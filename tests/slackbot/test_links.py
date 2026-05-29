from unittest import mock

import httpx

from imbi_slackbot import links, settings
from tests import helpers


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
        settings._slackbot_settings = None
        links._url_patterns = None

    def tearDown(self) -> None:
        settings._slackbot_settings = None
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
