import typing

import fastapi
import pydantic

status_router = fastapi.APIRouter()


class StatusResponse(pydantic.BaseModel):
    """Service operational status"""

    service: str = 'imbi'
    status: typing.Literal['ok', 'initializing', 'error']


@status_router.get('/status', response_model=StatusResponse, tags=['Status'])
async def get_status() -> StatusResponse:
    return StatusResponse(status='ok')
