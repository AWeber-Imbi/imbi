"""Tests for the document like endpoints."""

import datetime
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models


class DocumentLikeEndpointsTestCase(support.SharedAppTestCase):
    """Thumbs-up likes held as ``(:User)-[:LIKED]->(:Document)`` edges."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions
        from imbi.common import graph

        self.user = models.User(
            email='reader@example.com',
            display_name='Reader',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'document:read'},
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock()
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        # TestClient runs background tasks inline, so without this the
        # activity-feed emit would try to reach ClickHouse and burn
        # several minutes on connection backoff per request.
        self.emit = mock.AsyncMock()
        patcher = mock.patch(
            'imbi.api.endpoints.document_likes._document_events'
            '.emit_like_event',
            self.emit,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = fastapi.testclient.TestClient(self.test_app)

    @staticmethod
    def _state_row(
        like_count: int, liked_by_me: bool, project_id: str | None = None
    ) -> dict[str, object]:
        return {
            'like_count': like_count,
            'liked_by_me': liked_by_me,
            'project_id': project_id,
        }

    def test_like_returns_updated_state(self) -> None:
        self.mock_db.execute.return_value = [self._state_row(3, True)]
        response = self.client.put(
            '/organizations/engineering/documents/document-1/like'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {'like_count': 3, 'liked_by_me': True}
        )

    def test_like_preserves_original_timestamp(self) -> None:
        """A repeat like must not reorder the liker list.

        AGE has no ``ON CREATE SET``, so the MERGE writes
        ``coalesce(l.at, {now})`` -- the original ``at`` survives.
        """
        self.mock_db.execute.return_value = [self._state_row(1, True)]
        self.client.put('/organizations/engineering/documents/document-1/like')
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('MERGE (me)-[l:LIKED]->(d)', query)
        self.assertIn('SET l.at = coalesce(l.at, {now})', query)

    def test_like_unknown_document_is_404(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(
            '/organizations/engineering/documents/nope/like'
        )
        self.assertEqual(response.status_code, 404)

    def test_unlike_returns_updated_state(self) -> None:
        self.mock_db.execute.return_value = [self._state_row(0, False)]
        response = self.client.delete(
            '/organizations/engineering/documents/document-1/like'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {'like_count': 0, 'liked_by_me': False}
        )

    def test_unlike_is_idempotent(self) -> None:
        """Unliking something never liked succeeds rather than 404ing."""
        self.mock_db.execute.return_value = [self._state_row(2, False)]
        response = self.client.delete(
            '/organizations/engineering/documents/document-1/like'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['liked_by_me'])

    def test_like_count_uses_distinct_likers(self) -> None:
        """A duplicate edge must not double a document's like count."""
        self.mock_db.execute.return_value = [self._state_row(1, True)]
        self.client.put('/organizations/engineering/documents/document-1/like')
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('count(DISTINCT liker) AS like_count', query)

    def test_list_likers_most_recent_first(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'email': 'zoe@example.com',
                'display_name': 'Zoe',
                'liked_at': '2026-07-29T12:00:00+00:00',
            },
            {
                'email': 'abe@example.com',
                'display_name': None,
                'liked_at': '2026-07-28T12:00:00+00:00',
            },
        ]
        response = self.client.get(
            '/organizations/engineering/documents/document-1/likes'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(
            [row['principal'] for row in data],
            ['zoe@example.com', 'abe@example.com'],
        )
        self.assertEqual(data[0]['display_name'], 'Zoe')
        self.assertIsNone(data[1]['display_name'])

    def test_list_likers_rejects_bad_limit(self) -> None:
        response = self.client.get(
            '/organizations/engineering/documents/document-1/likes?limit=0'
        )
        self.assertEqual(response.status_code, 400)
