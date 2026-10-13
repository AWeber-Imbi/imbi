import os
import typing
import unittest
from unittest import mock

from imbi.common import sentry


def _event(url: str) -> dict[str, typing.Any]:
    frame = {'function': 'materialize', 'vars': {'handle': 'imh_secret'}}
    return {
        'request': {'url': url, 'data': {'handle': 'imh_secret'}},
        'exception': {'values': [{'stacktrace': {'frames': [dict(frame)]}}]},
        'threads': {'values': [{'stacktrace': {'frames': [dict(frame)]}}]},
    }


class BeforeSendTestCase(unittest.TestCase):
    def test_private_route_loses_body_and_frame_variables(self) -> None:
        for url in (
            'http://imbi/harness/executor/secret-materializations',
            'http://imbi/api/harness/executor/secret-materializations/',
        ):
            with self.subTest(url=url):
                event = sentry._before_send(_event(url), {})
                self.assertNotIn('data', event['request'])
                for key in ('exception', 'threads'):
                    (value,) = event[key]['values']
                    (frame,) = value['stacktrace']['frames']
                    self.assertEqual(frame, {'function': 'materialize'})

    def test_other_routes_keep_their_event(self) -> None:
        event = _event('http://imbi/harness/secret-resolutions')
        self.assertEqual(
            sentry._before_send(event, {}),
            _event('http://imbi/harness/secret-resolutions'),
        )
        self.assertEqual(sentry._before_send({}, {}), {})

    def test_init_sets_before_send(self) -> None:
        with (
            mock.patch.dict(os.environ, {'SENTRY_DSN': 'https://k@s/1'}),
            mock.patch('sentry_sdk.init') as init,
        ):
            sentry.init('test')
        self.assertIs(
            init.call_args.kwargs['before_send'], sentry._before_send
        )
