import typing

import fastapi
import pydantic

from imbi.common import lifespan

status_router = fastapi.APIRouter()


class StatusResponse(pydantic.BaseModel):
    """Service operational status"""

    service: str = 'imbi'
    status: typing.Literal['ok', 'initializing', 'error']


@status_router.get('/status', response_model=StatusResponse, tags=['Status'])
async def get_status(
    request: fastapi.Request, response: fastapi.Response
) -> StatusResponse:
    if lifespan.failed(request):
        response.status_code = 503
        return StatusResponse(status='error')
    return StatusResponse(status='ok')
