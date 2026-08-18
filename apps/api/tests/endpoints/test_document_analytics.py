"""Tests for document read-analytics reporting and its identity gate."""

import unittest
from unittest import mock

from imbi.api.endpoints import document_analytics
from imbi.api.endpoints.organizations import organizations_router


class IdentityGateTestCase(unittest.TestCase):
    """Who may see *which people* read a document.

    Aggregate readership is an operational signal; a named list is a
    different kind of data, so it needs both the permission and the
    organization's blessing.
    """

    @staticmethod
    def _auth(
        *, principal: str, permissions: set[str], is_admin: bool = False
    ):
        auth = mock.Mock()
        auth.permissions = permissions
        auth.principal_name = principal
        auth.is_admin = is_admin
        return auth

    def test_disabled_blocks_everyone(self) -> None:
        """Not even the author, and not even an admin."""
        for auth in (
            self._auth(
                principal='author@example.com',
                permissions={document_analytics.IDENTITY_PERMISSION},
            ),
            self._auth(
                principal='admin@example.com', permissions=set(), is_admin=True
            ),
        ):
            with self.subTest(principal=auth.principal_name):
                self.assertFalse(
                    document_analytics._may_see_identities(
                        auth, 'disabled', 'author@example.com'
                    )
                )

    def test_enabled_requires_the_permission(self) -> None:
        granted = self._auth(
            principal='lead@example.com',
            permissions={document_analytics.IDENTITY_PERMISSION},
        )
        denied = self._auth(principal='dev@example.com', permissions=set())
        self.assertTrue(
            document_analytics._may_see_identities(
                granted, 'enabled', 'author@example.com'
            )
        )
        self.assertFalse(
            document_analytics._may_see_identities(
                denied, 'enabled', 'author@example.com'
            )
        )

    def test_enabled_does_not_admit_the_author_alone(self) -> None:
        """Under 'enabled' the gate is the permission, not authorship."""
        author = self._auth(principal='author@example.com', permissions=set())
        self.assertFalse(
            document_analytics._may_see_identities(
                author, 'enabled', 'author@example.com'
            )
        )

    def test_authors_only_admits_the_author(self) -> None:
        author = self._auth(principal='author@example.com', permissions=set())
        stranger = self._auth(principal='other@example.com', permissions=set())
        self.assertTrue(
            document_analytics._may_see_identities(
                author, 'authors_only', 'author@example.com'
            )
        )
        self.assertFalse(
            document_analytics._may_see_identities(
                stranger, 'authors_only', 'author@example.com'
            )
        )

    def test_authors_only_still_admits_the_permission_holder(self) -> None:
        lead = self._auth(
            principal='lead@example.com',
            permissions={document_analytics.IDENTITY_PERMISSION},
        )
        self.assertTrue(
            document_analytics._may_see_identities(
                lead, 'authors_only', 'author@example.com'
            )
        )


class ScrollDepthTestCase(unittest.TestCase):
    """Per-reader depth has to survive the session dedup to be reported."""

    def test_dedup_carries_scroll_depth_through(self) -> None:
        """Dropping it here makes the readers query fail at ClickHouse."""
        self.assertIn(
            'argMax(max_scroll_pct, finalized_at)',
            document_analytics._DEDUPED_SESSIONS,
        )

    def test_readers_report_their_deepest_session(self) -> None:
        self.assertIn(
            'max(max_scroll_pct) AS max_scroll_pct',
            document_analytics._READERS_SQL,
        )


class ReadersHavingTestCase(unittest.TestCase):
    """The reader list must agree with the summary's reader count.

    The summary counts ``uniqExactIf(principal, is_read)``. Listing a
    principal who only viewed puts an extra avatar in the byline beside
    a count that never included them.
    """

    def test_view_only_principals_are_excluded(self) -> None:
        self.assertEqual(
            document_analytics._readers_having(False), 'HAVING reads > 0'
        )

    def test_pagination_keeps_the_reads_filter(self) -> None:
        having = document_analytics._readers_having(True)
        self.assertIn('reads > 0', having)
        self.assertIn('{cursor_ts:DateTime64(3)}', having)
        self.assertIn('{cursor_principal:String}', having)
        self.assertEqual(having.count('HAVING'), 1)
        self.assertIn(' AND ', having)


class SurfaceFilterTestCase(unittest.TestCase):
    """Human reads are the default answer; agents are opt-in."""

    def test_named_surface_is_bound_not_interpolated(self) -> None:
        fragment = document_analytics._surface_filter('web')
        self.assertIn('{surface:String}', fragment)
        self.assertNotIn("'web'", fragment)

    def test_all_drops_the_filter(self) -> None:
        self.assertEqual(document_analytics._surface_filter('all'), '')

    def test_self_excluded_unless_requested(self) -> None:
        """Editing a document must not inflate its readership."""
        self.assertIn(
            '{author:String}', document_analytics._self_filter(False)
        )
        self.assertEqual(document_analytics._self_filter(True), '')


class OrgReportRouteTestCase(unittest.TestCase):
    def test_org_report_is_a_sibling_of_documents(self) -> None:
        """The org report must not sit under ``/documents/``.

        Nested, its literal ``analytics`` segment competes with
        ``GET /documents/{document_id}`` and resolves correctly only
        while it happens to be registered first. As a sibling there is
        no ordering to get wrong.
        """
        paths = {route.path for route in organizations_router.routes}
        self.assertIn('/organizations/{org_slug}/document-analytics', paths)
        self.assertNotIn(
            '/organizations/{org_slug}/documents/analytics', paths
        )
