"""The unprefixed ``/status`` endpoint.

Deliberately outside ``IMBI_SCHEDULER_API_PREFIX``, matching imbi-assistant:
the Kubernetes probes address the pod directly and know nothing about the
prefix the task and run routes are mounted under. The chart aims both the
liveness and the readiness probe at this path -- see ``deployment.yaml``.
"""

import datetime
import os
import typing

import fastapi
import pydantic

router = fastapi.APIRouter()


class Status(pydantic.BaseModel):
    """What ``/status`` reports about this process."""

    environment: typing.Annotated[
        str,
        pydantic.Field(
            description='Operating environment', examples=['production']
        ),
    ]
    service: typing.Annotated[
        str, pydantic.Field(description='Service instance name')
    ] = 'imbi-scheduler'
    status: typing.Literal['ok', 'failing']
    version: typing.Annotated[
        str,
        pydantic.Field(description='Application version', examples=['0.0.0']),
    ]
    started_at: datetime.datetime


@router.get('/status', summary='Operational status', operation_id='getStatus')
def status_endpoint(*, request: fastapi.Request) -> Status:
    """Report that this process is up and serving.

    Answers from process state alone and touches no dependency. That is the
    intent rather than an omission: the chart points both probes here, so a
    check that queried Postgres or ClickHouse would make *liveness*
    dependency-shaped and restart healthy replicas during an outage they
    cannot fix and that restarting cannot shorten.
    """
    return Status(
        environment=os.environ.get('ENVIRONMENT', 'development'),
        status='ok',
        version=request.app.version,
        started_at=request.app.extra['started_at'],
    )
