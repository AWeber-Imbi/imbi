"""PagerDuty webhook-actions capability (v1 stub).

PagerDuty incident events are captured by the gateway's built-in event
recording, driven entirely by the ``pagerduty`` Integration selectors
(``identifier_selector`` / ``event_type_selector``) -- no custom action
is required for v1. This capability therefore advertises an empty action
catalog. It exists so the webhook surface is present as the home for
future event-triggered side effects (e.g. enriching an "active incident"
project fact or kicking a workflow) without a later manifest change.
"""

from __future__ import annotations

from imbi.common.plugins.base import (
    ActionDescriptor,
    WebhookActionsCapability,
    WebhookSignature,
)


class PagerDutyWebhookActions(WebhookActionsCapability):
    """Webhook-actions capability for PagerDuty; no actions in v1."""

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return []

    @classmethod
    def signature(cls) -> WebhookSignature:
        # V3 webhook subscriptions sign with a secret for each service,
        # which provisioning writes to the project's EXISTS_IN edge.
        return WebhookSignature(
            header='x-pagerduty-signature', prefix='v1=', secret='edge'
        )
