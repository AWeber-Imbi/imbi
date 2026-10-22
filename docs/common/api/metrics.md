# Metrics

The `imbi.common.metrics` module serves the Prometheus metrics of a
process at `/metrics`. `imbi-api`, `imbi-gateway` and `imbi-scheduler`
add the route.

## Add the route

Call `add_route()` on the root FastAPI app, not on a router with an API
prefix. The route is not in the OpenAPI schema.

```python
import fastapi

from imbi.common import metrics

app = fastapi.FastAPI()
metrics.add_route(app)
```

The route has no authentication. Do not expose it on a public route. The
in-cluster Prometheus scrapes it by pod IP.

## Registry

The route returns the default `prometheus_client` registry. Define
metrics with `prometheus_client` at module level and they show on the
route. For example, the [Iggy](iggy.md#metrics) client defines its
publish counters this way.

The services run one uvicorn worker per process, so the default registry
holds every metric of the process. The module does not use the
multiprocess mode of `prometheus_client`. If a service runs more than
one worker (`WEB_CONCURRENCY`), each scrape shows the metrics of one
worker only.

## API Reference

::: imbi.common.metrics.add_route

::: imbi.common.metrics.endpoint

::: imbi.common.metrics.PATH
