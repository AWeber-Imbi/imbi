"""Counters for webhook dispositions the logs alone cannot answer.

A dropped deployment event used to be a ``LOGGER.warning`` and nothing
else: the handler returned normally, so the ClickHouse activity row
recorded it as ``succeeded``.  "How many deployment events are we
losing, and why" was therefore a log-grep question, which is how the
losses went unnoticed until 738 deployments were stuck.

These are OpenTelemetry metrics, which the platform already carries the
API for (the ``otel`` extra).  Everything here degrades to a no-op when
``opentelemetry-api`` is not installed or no ``MeterProvider`` is
configured, so it is safe to call unconditionally.
"""

import typing

try:
    from opentelemetry import metrics as _otel_metrics
except ImportError:  # pragma: no cover - optional dependency
    _otel_metrics = None  # type: ignore[assignment]

#: One counter, one dimension: what happened to the event.
#:
#: - ``recorded`` -- attached to its release
#: - ``orphaned`` -- recorded without one, for the sweeper to attach
#: - ``unmapped_status`` -- the remote reported a state Imbi has no
#:   bucket for
#: - ``no_committish`` -- the rule's expression resolved to null
#: - ``lookup_failed`` -- the release lookup itself failed, so the
#:   event is dropped rather than mis-attributed
#: - ``release_missing`` -- the API rejected the write as 404
#: - ``write_failed`` -- the API rejected the write for any other
#:   reason, so the event is lost until something replays it
DEPLOYMENT_EVENTS = 'imbi.gateway.deployment_events'

Disposition = typing.Literal[
    'recorded',
    'orphaned',
    'unmapped_status',
    'no_committish',
    'lookup_failed',
    'release_missing',
    'write_failed',
]

_counter: typing.Any = None


def _deployment_counter() -> typing.Any:
    """Return the lazily-created counter, or ``None`` without OTel."""
    global _counter  # noqa: PLW0603
    if _otel_metrics is None:
        return None
    if _counter is None:
        _counter = _otel_metrics.get_meter(__name__).create_counter(
            DEPLOYMENT_EVENTS,
            description='Deployment webhook events by disposition.',
        )
    return _counter


def deployment_event(disposition: Disposition, project_id: str) -> None:
    """Count one deployment webhook event."""
    counter = _deployment_counter()
    if counter is not None:
        counter.add(1, {'disposition': disposition, 'project_id': project_id})
