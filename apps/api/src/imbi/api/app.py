import asyncio
import contextlib
import logging
import typing

import fastapi
from imbi_common import clickhouse, neo4j

from imbi_api import email, endpoints, openapi, storage, version
from imbi_api.middleware import rate_limit

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
        storage.initialize(),
        return_exceptions=True,
    )

    service_names = ['ClickHouse', 'Neo4j', 'Email', 'Storage']
    close_fns = [
        clickhouse.aclose,
        neo4j.aclose,
        email.aclose,
        storage.aclose,
    ]

    # Check if ClickHouse init returned False (failure without exception)
    if init_results[0] is False:
        LOGGER.error('ClickHouse initialization failed')
        # Clean up successfully initialized services
        cleanup_tasks = [
            close_fns[i]()
            for i in range(1, len(init_results))
            if not isinstance(init_results[i], Exception)
        ]
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        raise RuntimeError('ClickHouse initialization failed')

    # Check for initialization failures (exceptions)
    for i, result in enumerate(init_results):
        if isinstance(result, Exception):
            LOGGER.error(
                '%s initialization failed: %s',
                service_names[i],
                result,
            )
            # Clean up successfully initialized services
            cleanup_tasks = [
                close_fns[j]()
                for j in range(len(init_results))
                if j != i
                and not isinstance(init_results[j], Exception)
                and init_results[j] is not False
            ]
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            raise result

    # Refresh blueprint models for OpenAPI schema (must run after Neo4j init)
    try:
        await openapi.refresh_blueprint_models()
    except Exception as e:  # noqa: BLE001 - intentionally non-fatal
        LOGGER.warning('Failed to refresh blueprint models: %s', e)
        # Non-fatal - app can still start without enhanced OpenAPI schemas

    LOGGER.debug('Startup complete')
    yield
    shutdown_results = await asyncio.gather(
        neo4j.aclose(),
        clickhouse.aclose(),
        email.aclose(),
        storage.aclose(),
        return_exceptions=True,
    )
    # Log any shutdown failures but don't raise
    shutdown_names = ['Neo4j', 'ClickHouse', 'Email', 'Storage']
    for i, result in enumerate(shutdown_results):
        if isinstance(result, Exception):
            LOGGER.warning(
                '%s shutdown failed: %s',
                shutdown_names[i],
                result,
            )
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

    # Set custom OpenAPI schema generator with blueprint-enhanced models
    # FastAPI pattern: override openapi method to customize schema
    app.openapi = openapi.create_custom_openapi(app)  # type: ignore[method-assign]

    return app
