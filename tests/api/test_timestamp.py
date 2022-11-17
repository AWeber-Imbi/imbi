import datetime
import unittest

from dateutil import tz

from imbi import timestamp


class TimestampTests(unittest.TestCase):
    def test_format_and_parse(self):
        expectation = '2016-08-26 13:46:34-04:00'
        parsed = timestamp.parse(expectation)
        self.assertIsInstance(parsed, datetime.datetime)
        self.assertEqual(expectation, timestamp.isoformat(parsed))

    def test_isoformat_now(self):
        expectation = \
            datetime.datetime.utcnow().isoformat(' ').split('.')[0] + '+00:00'
        self.assertEqual(expectation, timestamp.isoformat())

    def test_parse_rfc822(self):
        expectation = datetime.datetime(1994,
                                        10,
                                        29,
                                        19,
                                        43,
                                        31,
                                        tzinfo=tz.tzoffset(None, 0))
        self.assertEqual(
            expectation,
            timestamp.parse_rfc822('Sat, 29 Oct 1994 19:43:31 GMT'))

    def test_parse_rfc822_invalid(self):
        self.assertIsNone(timestamp.parse_rfc822('Foo Bar'))

    def test_utcnow(self):
        self.assertEqual(
            timestamp.isoformat(timestamp.utcnow()),
            timestamp.isoformat(
                datetime.datetime.now(tz=tz.tzoffset(None, 0))))
