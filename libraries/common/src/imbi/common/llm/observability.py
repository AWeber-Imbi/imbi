"""PostHog AI observability for the services that call Anthropic.

``POSTHOG_AI_OBSERVABILITY`` turns it on (see :mod:`imbi.common.posthog`).
"""

import typing

import anthropic

from imbi.common import posthog


def client_class() -> type[anthropic.AsyncAnthropic]:
    """Return the PostHog wrapper when AI observability is on."""
    if not (posthog.ai_observability() and posthog.init()):
        return anthropic.AsyncAnthropic
    # Optional dependency: import only when the switch is on.
    from posthog.ai import anthropic as ph_anthropic

    return ph_anthropic.AsyncAnthropic


def tracking(subject: str, trace_id: str) -> dict[str, typing.Any]:
    """Keyword arguments that link an LLM call to a user and a trace.

    Only the PostHog wrapper takes them. Privacy mode is set on the
    PostHog client (``POSTHOG_AI_PRIVACY_MODE``).
    """
    return {
        'posthog_distinct_id': posthog.distinct_id(subject),
        'posthog_trace_id': trace_id,
    }
