import logging

import fastapi
from fastapi import responses
from fastapi.middleware import cors
from uvicorn.middleware import proxy_headers

from imbi.api import endpoints, lifespans, openapi, settings, version
from imbi.api.middleware import rate_limit
from imbi.common import access_log, graph, lifespan, sentry, valkey
from imbi.common.plugins.errors import PluginCredentialsMissing

LOGGER = logging.getLogger(__name__)


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi',
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            lifespans.clickhouse_hook,
            graph.graph_lifespan,
            lifespans.email_hook,
            lifespans.storage_hook,
            lifespans.anthropic_hook,
            valkey.valkey_lifespan,
            lifespans.score_worker_hook,
            lifespans.commit_sync_worker_hook,
            lifespans.pr_sync_worker_hook,
            lifespans.deployment_sync_worker_hook,
            lifespans.maintenance_worker_hook,
            lifespans.identity_refresh_hook,
        ),
        version=version,
        redoc_url=None,
        docs_url=None,
        license_info={
            'name': 'BSD 3-Clause',
            'url': 'https://github.com/AWeber-Imbi/imbi-api/blob/main/LICENSE',
        },
    )

    server_config = settings.ServerConfig()
    # Quiet both the unprefixed and ``/api``-prefixed status route
    # because the served path depends on IMBI_API_URL at startup;
    # listing both keeps the middleware deployment-agnostic.
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/api/status'},
    )
    app.add_middleware(
        cors.CORSMiddleware,
        allow_origins=server_config.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['authorization'],
    )

    # Honor X-Forwarded-For from trusted proxies so rate limiting keys
    # on the real client IP rather than the proxy address. Skipped
    # when forwarded_allow_ips is empty (dev/no-proxy deployments).
    if server_config.forwarded_allow_ips:
        app.add_middleware(
            proxy_headers.ProxyHeadersMiddleware,
            trusted_hosts=server_config.forwarded_allow_ips,
        )

    # Translate plugin credential failures (raised either at credential
    # lookup or from inside a plugin handler at runtime) into 503 so
    # callers don't see opaque 500s when an integration isn't configured.
    @app.exception_handler(PluginCredentialsMissing)
    async def _plugin_credentials_missing(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: PluginCredentialsMissing,
    ) -> responses.JSONResponse:
        LOGGER.warning('Plugin credentials missing: %s', exc)
        return responses.JSONResponse(
            status_code=503,
            content={'detail': str(exc)},
        )

    # Phase 5: Setup rate limiting middleware
    rate_limit.setup_rate_limiting(app)

    app.add_route('/docs', openapi.stoplights_html, include_in_schema=False)
    for router in endpoints.prefixed_routers:
        app.include_router(router, prefix=server_config.api_prefix)
    for router in endpoints.unprefixed_routers:
        app.include_router(router)

    # Set custom OpenAPI schema generator with blueprint-enhanced models
    # FastAPI pattern: override openapi method to customize schema
    app.openapi = openapi.create_custom_openapi(app)  # type: ignore[method-assign]

    return app
