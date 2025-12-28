import contextlib
import logging
import typing

import fastapi

from imbi import endpoints, neo4j, version

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def fastapi_lifespan(
    *_args: typing.Any, **_kwargs: typing.Any
) -> typing.AsyncIterator[None]:  # pragma: nocover
    """This is invoked by FastAPI for us to control startup and shutdown."""
    await neo4j.initialize()
    LOGGER.debug('Startup complete')
    yield
    await neo4j.aclose()
    LOGGER.debug('Clean shutdown complete')


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi', lifespan=fastapi_lifespan, version=version
    )
    for router in endpoints.routers:
        app.include_router(router)
    return app
