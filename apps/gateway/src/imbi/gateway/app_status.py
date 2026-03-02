import datetime
import os
import typing as t

import fastapi
import pydantic

from imbi_gateway import postgres

router = fastapi.APIRouter()


class Status(pydantic.BaseModel):
    environment: t.Annotated[
        str,
        pydantic.Field(
            description='Operating environment', examples=['production']
        ),
    ]
    service: t.Annotated[
        str, pydantic.Field(description='Service instance name')
    ] = 'imbi-gateway'
    status: t.Literal['ok', 'failing']
    version: t.Annotated[
        str,
        pydantic.Field(description='Application version', examples=['0.0.0']),
    ]
    started_at: datetime.datetime
    postgres: t.Annotated[
        postgres.Status, pydantic.Field(description='Current pool state')
    ]


@router.get('/status', summary='Operational status', operation_id='getStatus')
def status_endpoint(
    *, request: fastapi.Request, pool_state: postgres.PoolStatus
) -> Status:
    return Status(
        environment=os.environ.get('ENVIRONMENT', 'development'),
        status='ok',
        version=request.app.version,
        started_at=request.app.extra['started_at'],
        postgres=pool_state,
    )
