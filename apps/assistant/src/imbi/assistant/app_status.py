import datetime
import os
import typing as t

import fastapi
import pydantic

from imbi.common import graph

router = fastapi.APIRouter()


class Status(pydantic.BaseModel):
    environment: t.Annotated[
        str,
        pydantic.Field(
            description='Operating environment',
            examples=['production'],
        ),
    ]
    service: t.Annotated[
        str, pydantic.Field(description='Service instance name')
    ] = 'imbi-assistant'
    status: t.Literal['ok', 'failing']
    version: t.Annotated[
        str,
        pydantic.Field(description='Application version', examples=['0.0.0']),
    ]
    started_at: datetime.datetime


@router.get(
    '/status',
    summary='Operational status',
    operation_id='getStatus',
)
def status_endpoint(
    *,
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
) -> Status:
    # A closed pool means the lifespan was torn down while the process
    # kept serving; nothing reopens it, so report 503 and let the probe
    # replace the pod. This checks local state only, never the database.
    ok = db.opened
    if not ok:
        response.status_code = 503
    return Status(
        environment=os.environ.get('ENVIRONMENT', 'development'),
        status='ok' if ok else 'failing',
        version=request.app.version,
        started_at=request.app.extra['started_at'],
    )
