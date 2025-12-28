import typing

import fastapi
import pydantic

from imbi import version

status_router = fastapi.APIRouter()


class StatusResponse(pydantic.BaseModel):
    """Service operational status"""

    service: str = 'imbi'
    version: str = version
    status: typing.Literal['ok', 'initializing', 'error']


@status_router.get('/status', response_model=StatusResponse, tags=['status'])
async def get_status() -> StatusResponse:
    return StatusResponse(status='ok')
