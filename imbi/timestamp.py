"""
Handy Timestamp Methods

"""
import datetime
import typing
from email import utils

import arrow
import iso8601
from dateutil import tz


def age(value: typing.Union[datetime.datetime, str]) -> datetime.timedelta:
    """Return the age of a timestamp as a datetime.timedelta"""
    if isinstance(value, str):
        return utcnow() - iso8601.parse_date(value).datetime
    return utcnow() - value


def isoformat(value: typing.Optional[datetime.datetime] = None) -> str:
    """Format a datetime Object as an ISO-8601 timestamp without milliseconds.
    If the value is not returned, return the current time in UTC.

    """
    if not value:
        value = utcnow()
    output = value.isoformat(' ')
    if '.' in output:
        parts = output.split('.')
        return '{}{}'.format(parts[0], parts[1][6:])
    return output


def parse(value: str) -> datetime.datetime:
    """Parse an ISO-8601 formatted timestamp"""
    return iso8601.parse_date(value)


def parse_rfc822(value: str) -> typing.Optional[datetime.datetime]:
    """Parse an RFC-822 formatted timestamp value, returning a
    :class:`~datetime.datetime` instance.

    """
    parsed = utils.parsedate_tz(value)
    if not parsed:
        return None
    return datetime.datetime.fromtimestamp(
        utils.mktime_tz(parsed), tz.tzoffset(None, 0))


def to_utc(value: str) -> str:
    """Convert an ISO-8601 formatted timestamp to UTC"""
    return isoformat(arrow.get(value).to('UTC'))


def utcnow() -> datetime.datetime:
    """Return the current time in UTC"""
    return datetime.datetime.now(tz=tz.tzoffset(None, 0))
