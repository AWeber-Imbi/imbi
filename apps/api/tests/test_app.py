import email.utils
import os
import pathlib
import tempfile
import time
import typing
import unittest
import unittest.mock

import fastapi
import fastapi.testclient
import httpx

from imbi.api import app, settings, version
from imbi.common import access_log
from imbi.common.plugins import errors as plugin_errors


class CreateAppTestCase(unittest.TestCase):
    """Test cases for create_app function."""

    def test_create_app_returns_fastapi_instance(self) -> None:
        """Test that create_app returns a FastAPI instance."""
        application = app.create_app()
        self.assertIsInstance(application, fastapi.FastAPI)

    def test_create_app_has_correct_title(self) -> None:
        """Test that the app has the correct title."""
        application = app.create_app()
        self.assertEqual(application.title, 'Imbi')

    def test_create_app_has_correct_version(self) -> None:
        """Test that the app has the correct version."""
        application = app.create_app()
        self.assertEqual(application.version, version)

    def test_create_app_includes_routers(self) -> None:
        """Test that the app includes all routers."""
        application = app.create_app()
        # Check that the app has routes from our routers
        # At minimum, we should have the /status endpoint
        routes = [route.path for route in application.routes]
        self.assertIn('/status', routes)

    def test_create_app_has_lifespan(self) -> None:
        """Test that the app has a lifespan context manager configured."""
        application = app.create_app()
        self.assertIsNotNone(application.router.lifespan_context)

    def test_access_log_middleware_quiets_status_routes(self) -> None:
        """``/status`` and ``/api/status`` are silenced on success."""
        application = app.create_app()
        access_log_mw = next(
            (
                mw
                for mw in application.user_middleware
                if mw.cls is access_log.AccessLogMiddleware
            ),
            None,
        )
        self.assertIsNotNone(
            access_log_mw, 'AccessLogMiddleware was not installed'
        )
        assert access_log_mw is not None  # narrow for basedpyright
        quiet_paths = typing.cast(
            'set[str]', access_log_mw.kwargs['quiet_paths']
        )
        self.assertEqual(
            set(quiet_paths), {'/status', '/api/status', '/metrics'}
        )

    def test_metrics_returns_prometheus_text(self) -> None:
        # No `with`, so the lifespan does not run: the route needs none.
        client = fastapi.testclient.TestClient(app.create_app())
        response = client.get('/metrics')
        self.assertEqual(200, response.status_code)
        self.assertTrue(
            response.headers['content-type'].startswith('text/plain')
        )
        self.assertIn('imbi_iggy_published_total', response.text)
        self.assertIn('imbi_iggy_topic_status_up', response.text)


class ApiPrefixTestCase(unittest.TestCase):
    """Test cases for prefix derivation from IMBI_API_URL."""

    def setUp(self) -> None:
        super().setUp()
        settings.clear_caches()
        self.addCleanup(settings.clear_caches)

    def test_toml_url_prefixes_routes_and_oauth_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (pathlib.Path(tmpdir) / 'config.toml').write_text(
                '[server]\nurl = "https://imbi.example.com/api"\n'
            )
            original_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with unittest.mock.patch.dict(os.environ, {}, clear=True):
                    application = app.create_app()
                    callback = settings.oauth_callback_url('github')
            finally:
                os.chdir(original_cwd)
        paths = {route.path for route in application.routes}
        self.assertIn('/api/status', paths)
        self.assertNotIn('/status', paths)
        self.assertEqual(
            callback,
            'https://imbi.example.com/api/auth/oauth/github/callback',
        )

    def test_prefix_applies_to_routes_but_not_docs(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_API_URL': 'https://imbi.example.com/api'},
        ):
            application = app.create_app()
            paths = {route.path for route in application.routes}
        self.assertIn('/api/status', paths)
        self.assertNotIn('/status', paths)
        self.assertIn('/api/uploads/', paths)
        self.assertNotIn('/uploads/', paths)
        self.assertIn('/openapi.json', paths)
        self.assertIn('/docs', paths)
        self.assertIn('/metrics', paths)
        self.assertNotIn('/api/metrics', paths)

    def test_no_url_serves_at_root(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'IMBI_API_URL': ''}):
            application = app.create_app()
            paths = {route.path for route in application.routes}
        self.assertIn('/status', paths)
        self.assertIn('/uploads/', paths)

    def test_url_with_trailing_slash_in_path_is_normalized(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_API_URL': 'https://imbi.example.com/api/'},
        ):
            self.assertEqual(settings.ServerConfig().api_prefix, '/api')


class UpstreamErrorHandlerTestCase(unittest.TestCase):
    """Upstream and plugin failures map to an answer, not a bare 500."""

    def _get(self, exc: Exception) -> httpx.Response:
        application = app.create_app()

        async def _raise() -> None:
            raise exc

        application.add_api_route('/boom', _raise)
        client = fastapi.testclient.TestClient(
            application, raise_server_exceptions=False
        )
        return client.get('/boom')

    @staticmethod
    def _status_error(
        status: int, headers: dict[str, str] | None = None
    ) -> httpx.HTTPStatusError:
        request = httpx.Request('GET', 'https://api.github.test/x')
        return httpx.HTTPStatusError(
            f'HTTP {status}',
            request=request,
            response=httpx.Response(status, request=request, headers=headers),
        )

    def test_upstream_status_mapping(self) -> None:
        cases: list[tuple[int, dict[str, str] | None, int]] = [
            (404, None, 422),
            (422, None, 422),
            (403, None, 403),
            (403, {'x-ratelimit-remaining': '0'}, 503),
            (403, {'Retry-After': '30'}, 503),
            (429, None, 503),
            (500, None, 502),
            (502, None, 502),
        ]
        for upstream, headers, expected in cases:
            with self.subTest(upstream=upstream, headers=headers):
                response = self._get(self._status_error(upstream, headers))
                self.assertEqual(response.status_code, expected)
                if expected == 503:
                    self.assertIn('retry-after', response.headers)

    def test_rate_limit_forwards_retry_after(self) -> None:
        response = self._get(self._status_error(429, {'Retry-After': '42'}))
        self.assertEqual(response.headers['retry-after'], '42')

    def test_rate_limit_converts_http_date_retry_after(self) -> None:
        when = email.utils.formatdate(time.time() + 120, usegmt=True)
        response = self._get(self._status_error(429, {'Retry-After': when}))
        self.assertTrue(110 <= int(response.headers['retry-after']) <= 120)

    def test_plugin_unavailable_is_503(self) -> None:
        response = self._get(plugin_errors.PluginUnavailableError('down'))
        self.assertEqual(response.status_code, 503)

    def test_plugin_rate_limited_is_503_with_retry_after(self) -> None:
        response = self._get(plugin_errors.PluginRateLimited(time.time() + 90))
        self.assertEqual(response.status_code, 503)
        self.assertTrue(80 <= int(response.headers['retry-after']) <= 90)

    def test_plugin_rate_limited_in_the_past_waits_one_second(self) -> None:
        response = self._get(plugin_errors.PluginRateLimited(0))
        self.assertEqual(response.headers['retry-after'], '1')

    def test_installation_missing_is_403_app_not_installed(self) -> None:
        response = self._get(
            plugin_errors.PluginInstallationMissing('not installed')
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()['detail']['error'], 'app_not_installed'
        )

    def test_identity_access_denied_is_403_with_its_own_label(self) -> None:
        response = self._get(
            plugin_errors.PluginIdentityAccessDenied('no permission set')
        )
        self.assertEqual(response.status_code, 403)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'identity_access_denied')
        self.assertEqual(detail['message'], 'no permission set')
