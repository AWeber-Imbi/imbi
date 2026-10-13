import contextlib
import logging
import os
import urllib.parse
from collections import abc
from typing import Any

LOGGER = logging.getLogger(__name__)

#: Routes whose request body and frame variables can hold secrets: the
#: executor's secret materialization (ADR 0022). Matched on the end of
#: the path, so a prefix such as ``/api`` does not matter.
PRIVATE_PATH_SUFFIXES = ('/harness/executor/secret-materializations',)


def _before_send(event: Any, _hint: Any) -> Any:
    """Drop the request body and the local variables of every frame
    from an event of a private route (:data:`PRIVATE_PATH_SUFFIXES`)."""
    request = event.get('request') or {}
    path = urllib.parse.urlsplit(request.get('url') or '').path
    if not path.rstrip('/').endswith(PRIVATE_PATH_SUFFIXES):
        return event
    request.pop('data', None)
    for container in (event.get('exception'), event.get('threads')):
        for value in (container or {}).get('values') or []:
            for frame in (value.get('stacktrace') or {}).get('frames') or []:
                frame.pop('vars', None)
    return event


def _traces_sampler(sampling_context: dict[str, Any]) -> float:
    """Drop `/status` health-check transactions; sample everything else
    at `SENTRY_TRACES_SAMPLE_RATE` (default `0.0`).

    Matches `/status` and any prefixed variant (`/api/status`,
    `/assistant/status`, …) so health probes don't fill up Sentry quota.
    """
    asgi_scope = sampling_context.get('asgi_scope') or {}
    path = asgi_scope.get('path') or ''
    if path == '/status' or path.endswith('/status'):
        return 0.0
    raw_rate = os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.0')
    try:
        return float(raw_rate)
    except ValueError:
        LOGGER.warning(
            'Invalid SENTRY_TRACES_SAMPLE_RATE=%r; defaulting to 0.0',
            raw_rate,
        )
        return 0.0


@contextlib.asynccontextmanager
async def sentry_lifespan() -> abc.AsyncIterator[None]:
    """Async lifespan hook that initializes Sentry inside the event loop.

    Per the Sentry Python docs, init() should be called inside an async
    function for async apps to ensure async code is instrumented properly.
    Add this as the first hook in your service's Lifespan() composition.
    """
    init()
    yield


def init(service_name: str | None = None) -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured.

    Reads SENTRY_DSN from the environment. No-ops if the variable is
    absent or sentry-sdk is not installed. FastAPI/Starlette integrations
    are added automatically when those packages are available.

    Performance tracing is opt-in: set SENTRY_TRACES_SAMPLE_RATE to a
    value > 0 (e.g. `0.1` for 10%) to enable it. Defaults to `0.0`.
    `/status` health-check requests (and any prefixed variant like
    `/api/status`) are always dropped from traces regardless of the
    sample rate.

    Args:
        service_name: Override the service name sent to Sentry. Defaults
            to the SERVICE environment variable (set per-container in
            compose.yml), falling back to 'unknown'.
    """
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover
        return

    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        return

    name = service_name or os.environ.get('SERVICE', 'unknown')

    integrations: list[sentry_sdk.integrations.Integration] = []
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations = [StarletteIntegration(), FastApiIntegration()]
    except ImportError:
        pass

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        send_default_pii=False,
        server_name=name,
        traces_sampler=_traces_sampler,
        before_send=_before_send,
    )
    LOGGER.info('Sentry initialized for %s', name)
