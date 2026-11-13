import logging
import math
import time

import fastapi
import httpx
from fastapi import responses
from fastapi.middleware import cors
from uvicorn.middleware import proxy_headers

from imbi.api import (
    agent_tasks,
    endpoints,
    harness,
    lifespans,
    openapi,
    plugins,
    secret_broker,
    settings,
    version,
    workflows,
)
from imbi.api.auth import agent_api
from imbi.api.middleware import body_limit, rate_limit
from imbi.common import (
    access_log,
    graph,
    lifespan,
    metrics,
    posthog,
    relational,
    sentry,
    valkey,
)
from imbi.common.auth import permissions as common_permissions
from imbi.common.plugins.errors import (
    PluginCredentialsMissing,
    PluginInstallationMissing,
    PluginRateLimited,
    PluginUnavailableError,
)
from imbi.common.prompts import pool as prompt_pool

LOGGER = logging.getLogger(__name__)


def create_app() -> fastapi.FastAPI:
    # Agent API tokens (harness plan P7) work here, and nowhere else;
    # agent_api.guard refuses them on the sensitive routes.
    common_permissions.accept_agent_api_tokens()
    app = fastapi.FastAPI(
        title='Imbi',
        dependencies=[fastapi.Depends(agent_api.guard)],
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            lifespans.clickhouse_hook,
            lifespans.iggy_hook,
            lifespans.iggy_metrics_hook,
            graph.graph_lifespan,
            agent_tasks.store_lifespan,
            # Before harness: its fencer must be registered before the
            # lease sweep starts, and stay until the sweep stops.
            secret_broker.store_lifespan,
            harness.store_lifespan,
            workflows.store_lifespan,
            prompt_pool.pool_lifespan,
            lifespans.email_hook,
            lifespans.storage_hook,
            lifespans.anthropic_hook,
            valkey.valkey_lifespan,
            lifespans.score_worker_hook,
            lifespans.commit_sync_worker_hook,
            lifespans.pr_sync_worker_hook,
            lifespans.deployment_sync_worker_hook,
            lifespans.release_promote_worker_hook,
            lifespans.maintenance_worker_hook,
            lifespans.identity_refresh_hook,
            lifespans.document_read_sweeper_hook,
        ),
        version=version,
        redoc_url=None,
        docs_url=None,
        license_info={
            'name': 'BSD 3-Clause',
            'url': 'https://github.com/AWeber-Imbi/imbi-api/blob/main/LICENSE',
        },
    )

    server_config = settings.get_server_config()
    # Innermost, so that CORS and the access log wrap its 413. The
    # upload limit adds room for the multipart framing.
    app.add_middleware(
        body_limit.BodyLimitMiddleware,
        limit=server_config.max_request_body_bytes,
        path_limits={
            f'{server_config.api_prefix}/uploads': (
                settings.get_storage_settings().max_file_size + 1024 * 1024
            )
        },
    )
    # Quiet both the unprefixed and ``/api``-prefixed status route
    # because the served path depends on IMBI_API_URL at startup;
    # listing both keeps the middleware deployment-agnostic.
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/api/status', metrics.PATH},
    )
    app.add_middleware(
        cors.CORSMiddleware,
        allow_origins=server_config.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['authorization'],
        expose_headers=['Link'],
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

    # An Integration whose credential grants it nothing on the target
    # resource -- canonically a GitHub App that simply is not installed
    # on the repository. A terminal 403 rather than a 5xx: consuming
    # clients retry 5xx on the assumption that it is transient, and an
    # uninstalled App will still be uninstalled on the retry. The
    # discriminated ``detail.error`` (``app_not_installed``, or
    # ``identity_access_denied`` for a user identity with no grant) is
    # what an autonomous caller branches on so it can log the cause
    # instead of spinning.
    @app.exception_handler(PluginInstallationMissing)
    async def _plugin_installation_missing(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: PluginInstallationMissing,
    ) -> responses.JSONResponse:
        LOGGER.warning('Plugin grant missing (%s): %s', exc.error_code, exc)
        return responses.JSONResponse(
            status_code=403,
            content={
                'detail': {
                    'error': exc.error_code,
                    'message': str(exc),
                    'owner_repo': exc.owner_repo,
                    'integration_slug': exc.integration_slug,
                }
            },
        )

    # An upstream host (GitHub, AWS, ...) refused a plugin call and the
    # endpoint did not map the refusal itself. Answer with the nearest
    # status instead of a 500: the request or ref is bad (422), the
    # credential has no access (403), the host rate limits us (503 with
    # Retry-After), or the host failed (502).
    @app.exception_handler(httpx.HTTPStatusError)
    async def _upstream_status_error(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: httpx.HTTPStatusError,
    ) -> responses.JSONResponse:
        upstream = exc.response.status_code
        LOGGER.warning(
            'Upstream %s %s answered HTTP %s',
            exc.request.method,
            exc.request.url,
            upstream,
        )
        headers: dict[str, str] = {}
        rate_limited = upstream == 429 or (
            upstream == 403
            and (
                exc.response.headers.get('x-ratelimit-remaining') == '0'
                or 'retry-after' in exc.response.headers
            )
        )
        if upstream in (404, 422):
            status = 422
        elif rate_limited:
            status = 503
            headers['Retry-After'] = plugins.host_retry_after(exc.response)
        elif upstream == 403:
            status = 403
        else:
            status = 502
        return responses.JSONResponse(
            status_code=status,
            content={
                'detail': f'The upstream service answered HTTP {upstream}'
            },
            headers=headers,
        )

    # The endpoint found the organization, but a delete committed before
    # the store write took its lock (relational.lock_organization_shared).
    @app.exception_handler(relational.OrganizationDeleted)
    async def _organization_deleted(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: relational.OrganizationDeleted,
    ) -> responses.JSONResponse:
        return responses.JSONResponse(
            status_code=404, content={'detail': str(exc)}
        )

    @app.exception_handler(PluginUnavailableError)
    async def _plugin_unavailable(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: PluginUnavailableError,
    ) -> responses.JSONResponse:
        LOGGER.warning('Plugin unavailable: %s', exc)
        return responses.JSONResponse(
            status_code=503,
            content={'detail': str(exc)},
            headers={'Retry-After': '5'},
        )

    @app.exception_handler(PluginRateLimited)
    async def _plugin_rate_limited(  # pyright: ignore[reportUnusedFunction]
        _request: fastapi.Request,
        exc: PluginRateLimited,
    ) -> responses.JSONResponse:
        LOGGER.warning('Plugin rate limited: %s', exc)
        wait = max(1, math.ceil(exc.retry_at - time.time()))
        return responses.JSONResponse(
            status_code=503,
            content={'detail': str(exc)},
            headers={'Retry-After': str(wait)},
        )

    # Phase 5: Setup rate limiting middleware
    rate_limit.setup_rate_limiting(app)

    app.add_route('/docs', openapi.stoplights_html, include_in_schema=False)
    for router in endpoints.prefixed_routers:
        app.include_router(router, prefix=server_config.api_prefix)
    for router in endpoints.unprefixed_routers:
        app.include_router(router)
    agent_api.index(app, server_config.api_prefix)
    # On the app root, not under the API prefix: Prometheus scrapes it
    # by pod IP, and the public routes do not reach it.
    metrics.add_route(app)

    # Set custom OpenAPI schema generator with blueprint-enhanced models
    # FastAPI pattern: override openapi method to customize schema
    app.openapi = openapi.create_custom_openapi(app)  # type: ignore[method-assign]

    posthog.install(app)
    return app
