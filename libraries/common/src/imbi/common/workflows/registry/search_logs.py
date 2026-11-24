"""Search logs: get the log entries of a project, as its Logs tab does."""

import typing

import pydantic

from imbi.common.plugins import base
from imbi.common.workflows import step_type


class Params(pydantic.BaseModel):
    """The query parameters of ``GET .../projects/{id}/logs/``."""

    project_id: str = pydantic.Field(min_length=1)
    source: str | None = pydantic.Field(
        default=None,
        description='The slug of the logs integration. Empty: the default.',
    )
    environments: list[str] = pydantic.Field(
        default_factory=list,
        description=(
            'Environment slugs. Two or more: one search for each, merged, '
            'with no cursor.'
        ),
    )
    start_time: str | None = pydantic.Field(
        default=None,
        description='ISO 8601. Empty: 30 minutes before end_time.',
    )
    end_time: str | None = pydantic.Field(
        default=None, description='ISO 8601. Empty: now.'
    )
    cursor: str | None = pydantic.Field(
        default=None,
        description='next_cursor of an earlier search, for the next page.',
    )
    limit: int = pydantic.Field(default=100, ge=1, le=1000)
    filters: list[str] = pydantic.Field(
        default_factory=list,
        description=(
            'field:op:value, where op is eq, ne, contains, starts_with, '
            'or regex.'
        ),
    )
    levels: list[str] = pydantic.Field(
        default_factory=list, description='Severity levels, such as ERROR.'
    )


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    return {'project:logs:read'}


STEP = step_type.StepType(
    type='search_logs',
    category='action',
    label='Search logs',
    description='Gets the log entries of a project from its logs plugin.',
    params=Params,
    output=base.LogResult,
    sample_output={
        'entries': [
            {
                'timestamp': '2026-01-01T00:00:00Z',
                'message': 'sample',
                'level': 'ERROR',
                'raw': {},
            }
        ],
        'next_cursor': None,
        'total': 1,
        'warnings': [],
    },
    retries=2,
    required_permissions=required_permissions,
)
