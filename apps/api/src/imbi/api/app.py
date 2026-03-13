import fastapi
from imbi_common.lifespan import Lifespan

from imbi_api import endpoints, lifespans, openapi, version
from imbi_api.middleware import rate_limit


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi',
        lifespan=Lifespan(
            lifespans.clickhouse_hook,
            lifespans.neo4j_hook,
            lifespans.neo4j_setup_hook,
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

    # Phase 5: Setup rate limiting middleware
    rate_limit.setup_rate_limiting(app)

    for router in endpoints.routers:
        app.include_router(router)

    # Set custom OpenAPI schema generator with blueprint-enhanced models
    # FastAPI pattern: override openapi method to customize schema
    app.openapi = openapi.create_custom_openapi(app)  # type: ignore[method-assign]

    return app
