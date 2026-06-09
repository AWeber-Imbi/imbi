"""Tests for PagerDuty payload -> IncidentView mapping."""

import datetime
import unittest

from imbi_plugin_pagerduty.models import to_incident_view


class ToIncidentViewTestCase(unittest.TestCase):
    def test_full_payload(self) -> None:
        view = to_incident_view(
            {
                'id': 'PINC1',
                'title': 'High CPU',
                'status': 'resolved',
                'urgency': 'high',
                'created_at': '2026-06-01T14:00:00Z',
                'last_status_change_at': '2026-06-01T14:30:00Z',
                'html_url': 'https://acme.pagerduty.com/incidents/PINC1',
                'service': {'id': 'PSVC1', 'summary': 'Prod Web'},
            }
        )
        self.assertEqual(view.id, 'PINC1')
        self.assertEqual(view.status, 'resolved')
        self.assertEqual(view.urgency, 'high')
        self.assertEqual(view.service, 'Prod Web')
        self.assertEqual(
            view.created_at,
            datetime.datetime(2026, 6, 1, 14, 0, tzinfo=datetime.UTC),
        )
        # resolved incidents derive resolved_at from last_status_change_at
        self.assertEqual(
            view.resolved_at,
            datetime.datetime(2026, 6, 1, 14, 30, tzinfo=datetime.UTC),
        )

    def test_unresolved_has_no_resolved_at(self) -> None:
        view = to_incident_view(
            {
                'id': 'PINC2',
                'title': 't',
                'status': 'triggered',
                'created_at': '2026-06-01T14:00:00Z',
                'last_status_change_at': '2026-06-01T14:05:00Z',
                'html_url': 'https://x/PINC2',
            }
        )
        self.assertIsNone(view.resolved_at)
        self.assertIsNone(view.urgency)
        self.assertIsNone(view.service)

    def test_missing_created_at_defaults_now(self) -> None:
        view = to_incident_view({'id': 'PINC3', 'status': 'triggered'})
        self.assertIsInstance(view.created_at, datetime.datetime)
        self.assertEqual(view.title, '')
