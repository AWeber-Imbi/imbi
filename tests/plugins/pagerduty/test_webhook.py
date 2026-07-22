"""Tests for the PagerDuty webhook-actions capability (v1 stub)."""

import unittest

from imbi_plugin_pagerduty.webhook import PagerDutyWebhookActions


class WebhookActionsTestCase(unittest.TestCase):
    def test_actions_empty(self) -> None:
        self.assertEqual(PagerDutyWebhookActions.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(
            PagerDutyWebhookActions(), PagerDutyWebhookActions
        )
