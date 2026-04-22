import fastapi
from fastapi.middleware import cors
from imbi_common import graph, lifespan
from uvicorn.middleware import proxy_headers

from imbi_api import endpoints, lifespans, openapi, settings, version
from imbi_api.middleware import rate_limit


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi',
        lifespan=lifespan.Lifespan(
            lifespans.clickhouse_hook,
            graph.graph_lifespan,
            lifespans.email_hook,
            lifespans.storage_hook,
        ),
        version=version,
        redoc_url='/docs',
        docs_url=None,
        license_info={
            'name': 'BSD 3-Clause',
            'url': 'https://github.com/AWeber-Imbi/imbi-api/blob/main/LICENSE',
        },
    )

    server_config = settings.ServerConfig()
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

    # Phase 5: Setup rate limiting middleware
    rate_limit.setup_rate_limiting(app)

    for router in endpoints.routers:
        app.include_router(router)

    # Set custom OpenAPI schema generator with blueprint-enhanced models
    # FastAPI pattern: override openapi method to customize schema
    app.openapi = openapi.create_custom_openapi(app)  # type: ignore[method-assign]

    return app
