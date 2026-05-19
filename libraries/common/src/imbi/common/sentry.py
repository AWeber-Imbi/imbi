import contextlib
import logging
import os
from collections import abc

LOGGER = logging.getLogger(__name__)


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
        traces_sample_rate=float(
            os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')
        ),
    )
    LOGGER.info('Sentry initialized for %s', name)
