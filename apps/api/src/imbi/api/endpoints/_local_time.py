"""The requester's time zone and local date, from a ``tz`` query param.

A date that comes from the UTC clock is tomorrow for an evening user in
the Americas, so endpoints that show or use "today" take the browser's
IANA zone.
"""

import datetime
import typing
import zoneinfo

import fastapi


def _local_zone(
    tz: typing.Annotated[
        str,
        fastapi.Query(
            description=(
                'IANA time zone of the requester; dates use the date in '
                'this zone.'
            ),
        ),
    ] = 'UTC',
) -> zoneinfo.ZoneInfo:
    """The ``tz`` zone.

    An unknown zone is a 422: a silent UTC fallback would show
    tomorrow's date to an evening user in the Americas. The error has
    the same shape as other validation errors, so it matches the
    declared ``HTTPValidationError`` response.
    """
    try:
        return zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as err:
        raise fastapi.exceptions.RequestValidationError(
            [
                {
                    'type': 'value_error',
                    'loc': ('query', 'tz'),
                    'msg': f'Invalid time zone: {tz!r}',
                    'input': tz,
                }
            ]
        ) from err


LocalZone = typing.Annotated[zoneinfo.ZoneInfo, fastapi.Depends(_local_zone)]


def _local_today(zone: LocalZone) -> datetime.date:
    """Today's date in the requester's zone."""
    return datetime.datetime.now(zone).date()


LocalToday = typing.Annotated[datetime.date, fastapi.Depends(_local_today)]
