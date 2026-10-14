import os
import typing
import unittest
from unittest import mock

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
