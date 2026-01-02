import asyncio
import contextlib
import logging
import typing

import fastapi

from imbi import clickhouse, email, endpoints, neo4j, version
from imbi.middleware import rate_limit

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def fastapi_lifespan(
    *_args: typing.Any, **_kwargs: typing.Any
) -> typing.AsyncIterator[None]:  # pragma: nocover
    """This is invoked by FastAPI for us to control startup and shutdown."""
    init_results = await asyncio.gather(
        clickhouse.initialize(),
        neo4j.initialize(),
        email.initialize(),
        return_exceptions=True,
    )

    # Check if ClickHouse init returned False (failure without exception)
    if init_results[0] is False:
        LOGGER.error('ClickHouse initialization failed')
        # Clean up Neo4j and Email if they succeeded
        if not isinstance(init_results[1], Exception):
            await neo4j.aclose()
        if not isinstance(init_results[2], Exception):
            await email.aclose()
        raise RuntimeError('ClickHouse initialization failed')

    # Check for initialization failures (exceptions)
    for i, result in enumerate(init_results):
        if isinstance(result, Exception):
            service_name = ['ClickHouse', 'Neo4j', 'Email'][i]
            LOGGER.error('%s initialization failed: %s', service_name, result)
            # Clean up successfully initialized services
            cleanup_tasks = []
            if i > 0 and init_results[0] is True:
                cleanup_tasks.append(clickhouse.aclose())
            if i != 1 and not isinstance(init_results[1], Exception):
                cleanup_tasks.append(neo4j.aclose())
            if i != 2 and not isinstance(init_results[2], Exception):
                cleanup_tasks.append(email.aclose())
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            raise result

    LOGGER.debug('Startup complete')
    yield
    shutdown_results = await asyncio.gather(
        neo4j.aclose(),
        clickhouse.aclose(),
        email.aclose(),
        return_exceptions=True,
    )
    # Log any shutdown failures but don't raise
    for i, result in enumerate(shutdown_results):
        if isinstance(result, Exception):
            service_name = ['Neo4j', 'ClickHouse', 'Email'][i]
            LOGGER.warning('%s shutdown failed: %s', service_name, result)
    LOGGER.debug('Clean shutdown complete')


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi',
        lifespan=fastapi_lifespan,
        version=version,
        redoc_url='/docs',
        docs_url=None,
        license_info={
            'name': 'BSD 3-Clause',
            'url': 'https://github.com/AWeber-Imbi/imbi-api/blob/main/LICENSE',
        },
    )

    # Phase 5: Setup rate limiting middleware
    rate_limit.setup_rate_limiting(app)

    for router in endpoints.routers:
        app.include_router(router)
    return app
