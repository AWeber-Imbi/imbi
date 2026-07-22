"""Tests for identity attribution (v3).

Covers the two functions exported by :mod:`imbi_api.identity.attribution`:

* :func:`identity_integration_ids_for_project` -- walks a project's
  ``EXISTS_IN`` edges to Integration nodes and keeps only those whose
  plugin declares an ``identity`` capability.
* :func:`make_user_resolver` -- builds a subject -> Imbi-user-email
  resolver over the identity-capable Integration ids, including the
  multi-user-conflict path.
"""

from __future__ import annotations

import unittest
from unittest import mock

from imbi_api.identity import attribution


def _entry(has_identity: bool) -> mock.Mock:
    """A registry entry whose manifest declares (or not) ``identity``."""
    entry = mock.Mock()
    entry.manifest.get_capability.return_value = (
        object() if has_identity else None
    )
    return entry


class IdentityIntegrationIdsTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_to_identity_capable_integrations(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'integrations': '<agtype>'}]
        rows = [
            {'id': 'i1', 'plugin': 'github'},
            {'id': 'i2', 'plugin': 'ci'},
            {'id': 'i3', 'plugin': 'unknown'},
            {'id': None, 'plugin': 'github'},
        ]

        def fake_get(slug: str) -> mock.Mock:
            if slug == 'github':
                return _entry(has_identity=True)
            if slug == 'ci':
                return _entry(has_identity=False)
            raise attribution.PluginNotFoundError(slug)

        with (
            mock.patch.object(
                attribution.graph, 'parse_agtype', return_value=rows
            ),
            mock.patch.object(attribution, 'get_plugin', side_effect=fake_get),
        ):
            result = await attribution.identity_integration_ids_for_project(
                db, 'proj-1'
            )
        self.assertEqual(['i1'], result)
        _query, params, _columns = db.execute.await_args.args
        self.assertEqual({'project_id': 'proj-1'}, params)

    async def test_empty_when_project_has_no_integrations(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await attribution.identity_integration_ids_for_project(
            db, 'proj-1'
        )
        self.assertEqual([], result)


class MakeUserResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_none_when_no_integration_ids(self) -> None:
        db = mock.AsyncMock()
        self.assertIsNone(attribution.make_user_resolver(db, []))

    async def test_resolves_subject_to_email(self) -> None:
        db = mock.AsyncMock()
        db.match.return_value = [mock.Mock(email='alice@example.com')]
        with mock.patch.object(
            attribution.identity_repository,
            'find_user_by_subject',
            new=mock.AsyncMock(return_value='user-1'),
        ) as find:
            resolver = attribution.make_user_resolver(db, ['i1'])
            assert resolver is not None
            self.assertEqual('alice@example.com', await resolver('42'))
        find.assert_awaited_once_with(db, 'i1', '42')

    async def test_unmatched_subject_returns_none(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            attribution.identity_repository,
            'find_user_by_subject',
            new=mock.AsyncMock(return_value=None),
        ):
            resolver = attribution.make_user_resolver(db, ['i1'])
            assert resolver is not None
            self.assertIsNone(await resolver('99'))
        db.match.assert_not_called()

    async def test_same_user_across_integrations_dedupes(self) -> None:
        db = mock.AsyncMock()
        db.match.return_value = [mock.Mock(email='alice@example.com')]
        with mock.patch.object(
            attribution.identity_repository,
            'find_user_by_subject',
            new=mock.AsyncMock(side_effect=['user-1', 'user-1']),
        ):
            resolver = attribution.make_user_resolver(db, ['i1', 'i2'])
            assert resolver is not None
            self.assertEqual('alice@example.com', await resolver('42'))

    async def test_multiple_distinct_users_logs_and_returns_none(
        self,
    ) -> None:
        db = mock.AsyncMock()
        db.match.side_effect = [
            [mock.Mock(email='a@example.com')],
            [mock.Mock(email='b@example.com')],
        ]
        with mock.patch.object(
            attribution.identity_repository,
            'find_user_by_subject',
            new=mock.AsyncMock(side_effect=['user-1', 'user-2']),
        ):
            resolver = attribution.make_user_resolver(db, ['i1', 'i2'])
            assert resolver is not None
            with self.assertLogs(attribution.LOGGER, level='ERROR'):
                self.assertIsNone(await resolver('1'))
