"""Tests for the PagerDuty webhook-actions capability (v1 stub)."""

import unittest

from imbi.plugins.pagerduty.webhook import PagerDutyWebhookActions


class WebhookActionsTestCase(unittest.TestCase):
    def test_actions_empty(self) -> None:
        self.assertEqual(PagerDutyWebhookActions.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(
            PagerDutyWebhookActions(), PagerDutyWebhookActions
        )

    def test_signature_is_on_the_edge(self) -> None:
        signature = PagerDutyWebhookActions.signature()
        self.assertEqual(
            (signature.header, signature.prefix, signature.secret),
            ('x-pagerduty-signature', 'v1=', 'edge'),
        )
