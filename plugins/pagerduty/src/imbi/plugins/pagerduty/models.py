"""Mapping helpers from PagerDuty REST payloads to Imbi plugin models."""

from __future__ import annotations

import datetime
import typing

from imbi_common.plugins.base import IncidentView


def _parse_dt(value: object) -> datetime.datetime | None:
    """Parse a PagerDuty ISO-8601 timestamp into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def to_incident_view(raw: dict[str, typing.Any]) -> IncidentView:
    """Map a PagerDuty ``incident`` object to an :class:`IncidentView`.

    ``resolved_at`` is derived from ``last_status_change_at`` only when
    the incident is resolved (PagerDuty has no dedicated resolved-at
    field). ``created_at`` falls back to "now" if the payload omits it so
    a malformed row still renders rather than failing the whole list.
    """
    created = _parse_dt(raw.get('created_at')) or datetime.datetime.now(
        datetime.UTC
    )
    resolved = (
        _parse_dt(raw.get('last_status_change_at'))
        if raw.get('status') == 'resolved'
        else None
    )
    service_raw = raw.get('service')
    service_name: object = None
    if isinstance(service_raw, dict):
        service = typing.cast('dict[str, typing.Any]', service_raw)
        service_name = service.get('summary')
    return IncidentView(
        id=str(raw.get('id') or ''),
        title=str(raw.get('title') or raw.get('summary') or ''),
        status=str(raw.get('status') or ''),
        urgency=(
            str(raw['urgency']) if raw.get('urgency') is not None else None
        ),
        created_at=created,
        resolved_at=resolved,
        url=str(raw.get('html_url') or ''),
        service=str(service_name) if service_name else None,
    )
