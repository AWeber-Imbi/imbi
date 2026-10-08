"""Serve the Prometheus metrics of this process.

Each service adds `endpoint` at ``/metrics`` on its app root, outside
any API prefix, for the in-cluster Prometheus to scrape by pod IP. The
route has no authentication, so keep it off the public routes.

The services run one uvicorn worker per process, so the default
registry holds every metric of the process and the multiprocess mode
of ``prometheus_client`` is not necessary. If a service starts more
workers (``WEB_CONCURRENCY``), each scrape sees one worker only.
"""

import fastapi
import prometheus_client

PATH = '/metrics'


async def endpoint(_request: fastapi.Request) -> fastapi.Response:
    """Return the default registry in the Prometheus text format."""
    return fastapi.Response(
        prometheus_client.generate_latest(),
        media_type=prometheus_client.CONTENT_TYPE_LATEST,
    )


def add_route(app: fastapi.FastAPI) -> None:
    """Add the ``/metrics`` route to `app`, outside the OpenAPI schema."""
    app.add_route(PATH, endpoint, include_in_schema=False)
