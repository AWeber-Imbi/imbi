import os
import typing
import unittest
from unittest import mock

import httpx
from fastmcp.exceptions import ToolError

from imbi.common import sentry


def _event(
    url: str, module: str = 'imbi.api.endpoints.harness'
) -> dict[str, typing.Any]:
    frame = {'module': module, 'vars': {'handle': 'imh_secret'}}
    return {
        'request': {
            'url': url,
            'data': {'handle': 'imh_secret'},
            'query_string': 'handle=imh_secret',
        },
        'exception': {'values': [{'stacktrace': {'frames': [dict(frame)]}}]},
        'threads': {'values': [{'stacktrace': {'frames': [dict(frame)]}}]},
    }


def _transaction(url: str) -> dict[str, typing.Any]:
    return {
        'type': 'transaction',
        'transaction': '/harness/secret-resolutions',
        'request': {'url': url, 'data': {'handle': 'imh_secret'}},
    }


class ScrubTestCase(unittest.TestCase):
    def assert_no_vars(self, event: dict[str, typing.Any]) -> None:
        for key in ('exception', 'threads'):
            (value,) = event[key]['values']
            (frame,) = value['stacktrace']['frames']
            self.assertNotIn('vars', frame)

    def test_private_routes_lose_body_and_frame_variables(self) -> None:
        for path in (
            '/harness/executor/secret-materializations',
            '/api/harness/executor/secret-materializations/',
            '/api/harness/executor/secret-resolutions/1/release',
            '/harness/secret-resolutions',
            '/api/harness/secret-resolutions/',
        ):
            with self.subTest(path=path):
                event = sentry._scrub(_event('http://imbi' + path), {})
                self.assertNotIn('data', event['request'])
                self.assertNotIn('query_string', event['request'])
                self.assert_no_vars(event)

    def test_private_transactions_lose_the_body(self) -> None:
        for path in (
            '/api/harness/secret-resolutions',
            '/api/harness/executor/secret-materializations',
        ):
            with self.subTest(path=path):
                event = sentry._scrub(_transaction('http://imbi' + path), {})
                self.assertNotIn('data', event['request'])

    def test_broker_frames_lose_variables_on_any_route(self) -> None:
        event = sentry._scrub(
            _event(
                'http://imbi/api/organizations/o/secret-resolutions/',
                module='imbi.api.secret_broker.broker',
            ),
            {},
        )
        self.assert_no_vars(event)
        # Not a private route: the body and the query string stay.
        self.assertIn('data', event['request'])
        self.assertIn('query_string', event['request'])

    def test_other_routes_keep_their_event(self) -> None:
        for path in (
            '/api/harness/tasks/T-1/events',
            '/api/harness/secret-resolutionsx',
            '/api/organizations/o/secret-resolutions/',
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    sentry._scrub(_event('http://imbi' + path), {}),
                    _event('http://imbi' + path),
                )
        self.assertEqual(sentry._scrub({}, {}), {})

    def test_tool_errors_from_client_errors_are_dropped(self) -> None:
        def tool_error(status: int) -> BaseException:
            request = httpx.Request('GET', 'http://imbi-api/api/projects/')
            response = httpx.Response(status, request=request)
            cause = ValueError(f'HTTP error {status}')
            cause.__cause__ = httpx.HTTPStatusError(
                'error', request=request, response=response
            )
            error = ToolError('Error calling tool')
            error.__cause__ = cause
            return error

        def hint(error: BaseException) -> dict[str, typing.Any]:
            return {'exc_info': (type(error), error, error.__traceback__)}

        # IMBI-3M: the API refused a bad call; the model gets the error.
        self.assertIsNone(sentry._scrub({}, hint(tool_error(400))))
        # A server error or a plain client error is still reported.
        self.assertEqual(sentry._scrub({}, hint(tool_error(500))), {})
        not_a_tool = tool_error(400).__cause__
        assert not_a_tool is not None
        self.assertEqual(sentry._scrub({}, hint(not_a_tool)), {})

    def test_init_scrubs_errors_and_transactions(self) -> None:
        with (
            mock.patch.dict(os.environ, {'SENTRY_DSN': 'https://k@s/1'}),
            mock.patch('sentry_sdk.init') as init,
        ):
            sentry.init('test')
        kwargs = init.call_args.kwargs
        self.assertIs(kwargs['before_send'], sentry._scrub)
        self.assertIs(kwargs['before_send_transaction'], sentry._scrub)
        self.assertEqual(kwargs['max_request_body_size'], 'never')
