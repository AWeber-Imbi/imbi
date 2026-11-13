"""Tests for ``GET /cves/{cve_id}``."""

import datetime
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from imbi.api import cves, models
from imbi.api.auth import permissions


class CveEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=models.User(
                email='user@example.com',
                display_name='User',
                is_active=True,
                is_admin=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='test-session',
            auth_method='jwt',
            permissions={'component:read'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        # No lifespan: the endpoint needs no connection, only the patched
        # lookup.
        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

    def test_returns_the_record(self) -> None:
        record = cves.CveRecord(
            cve_id='CVE-2025-0001',
            state='PUBLISHED',
            updated_at=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
            cvss_severity='HIGH',
        )
        with mock.patch.object(
            cves,
            'lookup',
            mock.AsyncMock(return_value={'CVE-2025-0001': record}),
        ) as lookup:
            response = self.client.get('/cves/cve-2025-0001')
        self.assertEqual(200, response.status_code)
        self.assertEqual('HIGH', response.json()['cvss_severity'])
        lookup.assert_awaited_once_with(['CVE-2025-0001'])

    def test_unknown_id_is_404(self) -> None:
        with mock.patch.object(
            cves, 'lookup', mock.AsyncMock(return_value={})
        ):
            response = self.client.get('/cves/CVE-2025-0404')
        self.assertEqual(404, response.status_code)

    def test_needs_component_read(self) -> None:
        self.auth_context.permissions = set()
        response = self.client.get('/cves/CVE-2025-0001')
        self.assertEqual(403, response.status_code)
