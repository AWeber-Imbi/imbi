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

from imbi.common import lifespan

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
    #: ``'failing'`` only when the lifespan exited while the process kept
    #: serving -- see the endpoint.
    status: typing.Literal['ok', 'failing']
    version: typing.Annotated[
        str,
        pydantic.Field(description='Application version', examples=['0.0.0']),
    ]
    started_at: datetime.datetime


@router.get('/status', summary='Operational status', operation_id='getStatus')
def status_endpoint(
    *, request: fastapi.Request, response: fastapi.Response
) -> Status:
    """Report that this process is up and serving.

    Answers from process state alone and touches no dependency. It returns
    503 ``'failing'`` only when the lifespan exited while uvicorn kept
    serving: its pools are closed and nothing reopens them, so the pod must
    be replaced. The obvious further change — add a readiness check over the
    store pool, the ClickHouse client and the engine task — is the one to
    resist here.

    The chart points **both** the liveness and the readiness probe at this
    path (see ``helm/imbi/templates/deployment.yaml``). So a dependency-aware
    answer cannot be scoped to readiness: it would make *liveness*
    dependency-shaped too, and a Postgres blip would restart every replica —
    discarding in-flight ticks to fix nothing, since restarting does not
    shorten a database outage.

    Readiness signalling also earns its keep only when some replicas are
    healthier than others, and here none ever are: every replica shares one
    Postgres and one ClickHouse, so a dependency check fails them together and
    leaves no healthier endpoint for traffic to move to.

    Real readiness therefore needs a **separate path that only the readiness
    probe uses**, plus the chart change to point at it. That is a deliberate
    piece of work, not an edit to this function.
    """
    ok = not lifespan.failed(request)
    if not ok:
        response.status_code = 503
    return Status(
        environment=os.environ.get('ENVIRONMENT', 'development'),
        status='ok' if ok else 'failing',
        version=request.app.version,
        started_at=request.app.extra['started_at'],
    )
