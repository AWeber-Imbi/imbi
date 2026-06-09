"""PagerDuty incidents plugin.

Live-queries PagerDuty for the incidents on a project's service and
returns them for the project-detail Incidents tab. Read-only: there is
no local incident store, and a project with no resolvable service yields
an empty result rather than an error.
"""

from __future__ import annotations

import datetime
import typing

from imbi_common.plugins.base import (
    CredentialField,
    IncidentResult,
    IncidentsPlugin,
    PluginContext,
    PluginManifest,
)

from imbi_plugin_pagerduty import _client, _services
from imbi_plugin_pagerduty.models import to_incident_view

_API_CREDENTIALS = [
    CredentialField(
        name='api_key',
        label='PagerDuty REST API key',
        description='A read-capable PagerDuty REST API key.',
        required=True,
    )
]


class PagerDutyIncidentsPlugin(IncidentsPlugin):
    """Live-query PagerDuty incidents for a project's service."""

    manifest = PluginManifest(
        slug='pagerduty-incidents',
        name='PagerDuty Incidents',
        description=(
            "Live-query PagerDuty for the incidents on a project's "
            'service and render them on the Incidents tab.'
        ),
        plugin_type='incidents',
        auth_type='api_token',
        cacheable=True,
        credentials=_API_CREDENTIALS,
    )

    @staticmethod
    def _params(
        service_id: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        statuses: list[str] | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, str | list[str]]:
        # PagerDuty expects bracketed array params (``service_ids[]``,
        # ``statuses[]``); a list value makes httpx emit one entry per
        # element rather than a comma-joined string.
        params: dict[str, str | list[str]] = {
            'service_ids[]': service_id,
            'since': start_time.isoformat(),
            'until': end_time.isoformat(),
            'offset': str(_offset(cursor)),
            'limit': str(limit),
            'sort_by': 'created_at:desc',
        }
        if statuses:
            params['statuses[]'] = list(statuses)
        return params

    async def list_incidents(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        *,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        statuses: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> IncidentResult:
        async with _client.client(credentials) as client:
            service_id = await _services.resolve_service_id(client, ctx)
            if service_id is None:
                return IncidentResult()
            response = await client.get(
                '/incidents',
                params=self._params(
                    service_id, start_time, end_time, statuses, cursor, limit
                ),
            )
            response.raise_for_status()
            payload: dict[str, typing.Any] = response.json()
        rows: list[dict[str, typing.Any]] = payload.get('incidents') or []
        next_cursor = (
            str(_offset(cursor) + limit) if payload.get('more') else None
        )
        total = payload.get('total')
        return IncidentResult(
            incidents=[to_incident_view(row) for row in rows],
            next_cursor=next_cursor,
            total=total if isinstance(total, int) else None,
        )


def _offset(cursor: str | None) -> int:
    """Decode the opaque cursor (a PagerDuty offset) into an int."""
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0
