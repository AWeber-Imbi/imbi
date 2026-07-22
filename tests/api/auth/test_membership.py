"""Tests for default-role auto-assignment on login."""

import unittest
from unittest import mock

from imbi.api.auth import membership


def _agtype_passthrough(value):
    return value


class EnsureUserMembershipTestCase(unittest.IsolatedAsyncioTestCase):
    """Cover the decision branches of ensure_user_membership."""

    async def test_assigns_when_no_membership_and_sole_org(self) -> None:
        """User with no MEMBER_OF gets default role in the sole org."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'edges': 0}],
            [{'slug': 'default'}],
            [{'slugs': ['aweber']}],
            [{'email': 'u@example.com'}],
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertEqual(result, 'default')
        # Verify the CREATE call used the sole org slug + default role
        create_args = mock_db.execute.await_args_list[-1].args
        self.assertEqual(
            create_args[1],
            {
                'email': 'u@example.com',
                'org_slug': 'aweber',
                'role_slug': 'default',
            },
        )

    async def test_prefers_default_org_when_multiple(self) -> None:
        """With multiple orgs, the slug='default' org is chosen."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'edges': 0}],
            [{'slug': 'default'}],
            [{'slugs': ['aweber', 'default', 'other']}],
            [{'email': 'u@example.com'}],
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertEqual(result, 'default')
        create_args = mock_db.execute.await_args_list[-1].args
        self.assertEqual(create_args[1]['org_slug'], 'default')

    async def test_skips_when_user_already_has_membership(self) -> None:
        """User with any MEMBER_OF edge is left alone."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [[{'edges': 1}]]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertIsNone(result)
        self.assertEqual(mock_db.execute.await_count, 1)

    async def test_skips_when_no_default_role(self) -> None:
        """No is_default role -> no assignment, no exception."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'edges': 0}],
            [],  # no default role row
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertIsNone(result)

    async def test_skips_when_multiple_orgs_and_no_default(self) -> None:
        """Ambiguous orgs (>1 and none named 'default') -> skip."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'edges': 0}],
            [{'slug': 'default'}],
            [{'slugs': ['orgA', 'orgB']}],
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertIsNone(result)
        # The CREATE call must not have run
        self.assertEqual(mock_db.execute.await_count, 3)

    async def test_skips_when_no_orgs(self) -> None:
        """No organizations at all -> skip."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'edges': 0}],
            [{'slug': 'default'}],
            [{'slugs': []}],
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertIsNone(result)

    async def test_skips_when_user_node_missing(self) -> None:
        """Membership-count query empty -> skip without error."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [[]]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=_agtype_passthrough,
        ):
            result = await membership.ensure_user_membership(
                mock_db, 'u@example.com'
            )

        self.assertIsNone(result)
