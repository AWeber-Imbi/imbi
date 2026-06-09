"""Tests for the service-writeback / EXISTS_IN helpers.

Covers :func:`lookup_project_exists_in`, :func:`merge_project_links`,
and :func:`persist_service_writeback` in
:mod:`imbi_api.endpoints._helpers`.
"""

import asyncio
import json
import unittest
import unittest.mock as mock

from imbi_common.plugins.base import PluginContext, ServiceWriteback

from imbi_api.endpoints import _helpers


def _ctx(**kwargs: object) -> PluginContext:
    base: dict[str, object] = {
        'project_id': 'proj-1',
        'project_slug': 'proj',
        'org_slug': 'org-1',
    }
    base.update(kwargs)
    return PluginContext(**base)  # type: ignore[arg-type]


class LookupProjectExistsInTestCase(unittest.TestCase):
    def test_returns_connections(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'service_slug': 'github-enterprise-cloud',
                'identifier': '134741',
                'canonical_url': 'https://api.x.ghe.com/repositories/134741',
            },
            {
                'service_slug': 'sonarqube',
                'identifier': 'conv:account',
                'canonical_url': None,
            },
        ]
        result = asyncio.run(_helpers.lookup_project_exists_in(db, 'proj-1'))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].service_slug, 'github-enterprise-cloud')
        # numeric-looking identifiers round-trip back to a string
        self.assertEqual(result[0].identifier, '134741')
        self.assertEqual(
            result[0].canonical_url,
            'https://api.x.ghe.com/repositories/134741',
        )
        self.assertEqual(result[1].service_slug, 'sonarqube')
        self.assertIsNone(result[1].canonical_url)

    def test_empty_on_lookup_failure(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('boom')
        result = asyncio.run(_helpers.lookup_project_exists_in(db, 'proj-1'))
        self.assertEqual(result, [])

    def test_skips_rows_without_slug(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'service_slug': None, 'identifier': 'x', 'canonical_url': None}
        ]
        result = asyncio.run(_helpers.lookup_project_exists_in(db, 'proj-1'))
        self.assertEqual(result, [])


class MergeProjectLinksTestCase(unittest.TestCase):
    def test_add_and_remove(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            _helpers,
            'lookup_project_links',
            new=mock.AsyncMock(return_value={'old': 'https://old', 'k': 'v'}),
        ):
            changed = asyncio.run(
                _helpers.merge_project_links(
                    db,
                    'proj-1',
                    add={'github': 'https://gh'},
                    remove=['old'],
                )
            )
        self.assertTrue(changed)
        db.execute.assert_awaited_once()
        params = db.execute.await_args.args[1]
        written = json.loads(params['links'])
        self.assertEqual(written, {'k': 'v', 'github': 'https://gh'})

    def test_no_op_returns_false(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            _helpers,
            'lookup_project_links',
            new=mock.AsyncMock(return_value={'k': 'v'}),
        ):
            changed = asyncio.run(
                _helpers.merge_project_links(db, 'proj-1', add={'k': 'v'})
            )
        self.assertFalse(changed)
        db.execute.assert_not_awaited()


class PersistServiceWritebackTestCase(unittest.TestCase):
    def test_noop_when_no_writeback(self) -> None:
        db = mock.AsyncMock()
        asyncio.run(_helpers.persist_service_writeback(db, _ctx()))
        db.execute.assert_not_awaited()

    def test_skips_without_bound_slug(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx(
            service_writeback=ServiceWriteback(
                identifier='1', canonical_url='https://api/1'
            )
        )
        asyncio.run(_helpers.persist_service_writeback(db, ctx))
        db.execute.assert_not_awaited()

    def test_upsert_path(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx(
            third_party_service_slug='github-enterprise-cloud',
            service_writeback=ServiceWriteback(
                identifier='134741',
                canonical_url='https://api.x.ghe.com/repositories/134741',
                dashboard_links={'github-enterprise-cloud': 'https://x/o/r'},
            ),
        )
        with (
            mock.patch.object(
                _helpers, '_merge_exists_in', new=mock.AsyncMock()
            ) as merge_edge,
            mock.patch.object(
                _helpers,
                'merge_project_links',
                new=mock.AsyncMock(return_value=True),
            ) as merge_links,
        ):
            asyncio.run(_helpers.persist_service_writeback(db, ctx))
        merge_edge.assert_awaited_once_with(
            db,
            'org-1',
            'proj-1',
            'github-enterprise-cloud',
            '134741',
            'https://api.x.ghe.com/repositories/134741',
            None,
        )
        merge_links.assert_awaited_once()
        self.assertEqual(
            merge_links.await_args.kwargs['add'],
            {'github-enterprise-cloud': 'https://x/o/r'},
        )

    def test_upsert_path_passes_webhook_secret(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx(
            third_party_service_slug='pagerduty',
            service_writeback=ServiceWriteback(
                identifier='PSVC1',
                canonical_url='https://api.pagerduty.com/services/PSVC1',
                webhook_secret_enc='gAAAAAB-ciphertext',
            ),
        )
        with (
            mock.patch.object(
                _helpers, '_merge_exists_in', new=mock.AsyncMock()
            ) as merge_edge,
            mock.patch.object(
                _helpers,
                'merge_project_links',
                new=mock.AsyncMock(return_value=False),
            ),
        ):
            asyncio.run(_helpers.persist_service_writeback(db, ctx))
        # secret is threaded through as the trailing positional arg
        self.assertEqual(merge_edge.await_args.args[6], 'gAAAAAB-ciphertext')

    def test_remove_path(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx(
            third_party_service_slug='github-enterprise-cloud',
            service_writeback=ServiceWriteback(
                identifier='1',
                canonical_url='https://api/1',
                dashboard_links={'github-enterprise-cloud': 'https://x/o/r'},
                remove=True,
            ),
        )
        with (
            mock.patch.object(
                _helpers, '_delete_exists_in', new=mock.AsyncMock()
            ) as delete_edge,
            mock.patch.object(
                _helpers,
                'merge_project_links',
                new=mock.AsyncMock(return_value=True),
            ) as merge_links,
        ):
            asyncio.run(_helpers.persist_service_writeback(db, ctx))
        delete_edge.assert_awaited_once_with(
            db, 'org-1', 'proj-1', 'github-enterprise-cloud'
        )
        self.assertEqual(
            list(merge_links.await_args.kwargs['remove']),
            ['github-enterprise-cloud'],
        )

    def test_write_failure_is_swallowed(self) -> None:
        db = mock.AsyncMock()
        ctx = _ctx(
            third_party_service_slug='github',
            service_writeback=ServiceWriteback(
                identifier='1', canonical_url='https://api/1'
            ),
        )
        with mock.patch.object(
            _helpers,
            '_merge_exists_in',
            new=mock.AsyncMock(side_effect=RuntimeError('db down')),
        ):
            # must not raise
            asyncio.run(_helpers.persist_service_writeback(db, ctx))


class MergeExistsInTestCase(unittest.TestCase):
    def test_omits_secret_when_none(self) -> None:
        db = mock.AsyncMock()
        asyncio.run(
            _helpers._merge_exists_in(
                db, 'org-1', 'proj-1', 'pagerduty', 'PSVC1', 'https://api/1'
            )
        )
        query, params = db.execute.await_args.args[:2]
        self.assertNotIn('webhook_secret_enc', query)
        self.assertNotIn('webhook_secret_enc', params)

    def test_sets_secret_when_provided(self) -> None:
        db = mock.AsyncMock()
        asyncio.run(
            _helpers._merge_exists_in(
                db,
                'org-1',
                'proj-1',
                'pagerduty',
                'PSVC1',
                'https://api/1',
                'gAAAAAB-ciphertext',
            )
        )
        query, params = db.execute.await_args.args[:2]
        self.assertIn('ei.webhook_secret_enc = {webhook_secret_enc}', query)
        self.assertEqual(params['webhook_secret_enc'], 'gAAAAAB-ciphertext')


if __name__ == '__main__':
    unittest.main()
