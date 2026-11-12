import hashlib
import json
import typing
import unittest
from unittest import mock

import fastapi
import posthog as posthog_sdk
from fastapi import testclient
from posthog.integrations import asgi

from imbi.common import posthog

_ENV = {'POSTHOG_API_KEY': 'phc_test', 'SERVICE': 'imbi-test'}


class PostHogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[dict[str, typing.Any]] = []
        self.addCleanup(self._reset)

    @staticmethod
    def _reset() -> None:
        if posthog_sdk.default_client is not None:
            posthog_sdk.default_client.disabled = True
        posthog_sdk.default_client = None
        posthog._started = False
        posthog_sdk.api_key = None
        posthog_sdk.before_send = None
        posthog_sdk.super_properties = None

    def _record(self) -> None:
        """Keep each event after Imbi's scrubber, and send none."""
        # Module-level calls copy this setting onto the client each time.
        scrub = posthog_sdk.before_send
        assert scrub is not None

        def keep(message: dict[str, typing.Any]) -> None:
            self.events.append(scrub(message))

        posthog_sdk.before_send = keep
        posthog_sdk.setup()

    def _app(self) -> fastapi.FastAPI:
        app = fastapi.FastAPI()

        @app.get('/boom')
        async def boom() -> None:
            # Built at run time: the source context lines PostHog sends
            # must not contain it, only a frame variable could.
            handle = 'imh_' + 'secret'  # noqa: F841 - must not be sent
            raise RuntimeError('boom')

        posthog.install(app)
        return app

    def test_off_without_key(self) -> None:
        with mock.patch.dict('os.environ', {}, clear=True):
            app = self._app()
            self.assertFalse(posthog.init())
            posthog.capture_exception(RuntimeError('x'))
        self.assertIsNone(posthog_sdk.default_client)
        self.assertNotIn(
            asgi.PosthogASGIMiddleware,
            [m.cls for m in app.user_middleware],
        )

    def test_error_tracking_switch_off(self) -> None:
        env = {**_ENV, 'POSTHOG_ERROR_TRACKING': 'false'}
        with mock.patch.dict('os.environ', env, clear=True):
            app = self._app()
        self.assertNotIn(
            asgi.PosthogASGIMiddleware,
            [m.cls for m in app.user_middleware],
        )

    def test_unhandled_error_gives_one_scrubbed_event(self) -> None:
        with mock.patch.dict('os.environ', _ENV, clear=True):
            app = self._app()
            self._record()
            client = testclient.TestClient(app, raise_server_exceptions=False)
            response = client.get(
                '/boom?token=secret',
                headers={
                    'authorization': 'Bearer secret',
                    'cookie': 'session=secret',
                    'x-forwarded-for': '203.0.113.9',
                },
            )
        self.assertEqual(response.status_code, 500)
        exceptions = [e for e in self.events if e['event'] == '$exception']
        self.assertEqual(len(exceptions), 1)
        properties = exceptions[0]['properties']
        self.assertEqual(properties['service'], 'imbi-test')
        self.assertEqual(properties['$request_path'], '/boom')
        self.assertNotIn('$ip', properties)
        body = json.dumps(exceptions[0], default=str)
        for secret in ('token=secret', 'Bearer', 'session=', 'imh_secret'):
            self.assertNotIn(secret, body)

    def test_capture_exception(self) -> None:
        with mock.patch.dict('os.environ', _ENV, clear=True):
            posthog.init()
            self._record()
            posthog.capture_exception(RuntimeError('handled'))
        self.assertEqual([e['event'] for e in self.events], ['$exception'])

    def test_distinct_id_hashes_the_subject(self) -> None:
        self.assertEqual(
            posthog.distinct_id(' A@B.c '),
            hashlib.sha256(b'a@b.c').hexdigest(),
        )

    def test_switches(self) -> None:
        env = {
            **_ENV,
            'POSTHOG_MCP_ANALYTICS': 'true',
            'POSTHOG_AI_OBSERVABILITY': '1',
        }
        with mock.patch.dict('os.environ', env, clear=True):
            self.assertTrue(posthog.mcp_analytics())
            self.assertTrue(posthog.ai_observability())
        with mock.patch.dict('os.environ', _ENV, clear=True):
            self.assertFalse(posthog.mcp_analytics())
            self.assertFalse(posthog.ai_observability())
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertFalse(posthog.error_tracking())

    def test_scrub_drops_ip_and_mcp_payloads(self) -> None:
        message = {
            'event': '$mcp_tool_call',
            'properties': {
                '$ip': '203.0.113.9',
                '$mcp_tool_name': 'list_projects',
                '$mcp_parameters': {'token': 'secret'},
                '$mcp_response': 'secret',
                '$mcp_error_message': 'secret',
                '$mcp_intent': 'secret',
            },
        }
        self.assertEqual(
            posthog._scrub(message)['properties'],
            {'$mcp_tool_name': 'list_projects'},
        )

    def test_scrub_redacts_emails_in_paths(self) -> None:
        message = {
            'event': '$exception',
            'properties': {
                '$request_path': '/api/users/a.b@example.com/tokens',
                '$current_url': 'http://imbi/api/users/a%40example.com',
            },
        }
        self.assertEqual(
            posthog._scrub(message)['properties'],
            {
                '$request_path': '/api/users/[email]/tokens',
                '$current_url': 'http://imbi/api/users/[email]',
            },
        )
