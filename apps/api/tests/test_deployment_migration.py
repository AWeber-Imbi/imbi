"""Tests for the phase-3 deployment data cleanup operations."""

from __future__ import annotations

import json
import typing
import unittest
from unittest import mock

from imbi.api import deployment_migration

_RESOLVE = 'imbi.api.endpoints.project_deployments.resolve_remote_tags'


def _release(
    node_id: str,
    tag: str = '1.0.0',
    committish: str = 'aaaaaaa',
    created_at: str = '2026-01-01T00:00:00+00:00',
    **extra: object,
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'tag': tag,
        'committish': committish,
        'created_at': created_at,
        **extra,
    }


def _event(
    timestamp: str,
    status: str = 'success',
    run_id: str | None = None,
    **extra: object,
) -> dict[str, typing.Any]:
    entry: dict[str, typing.Any] = {'timestamp': timestamp, 'status': status}
    if run_id is not None:
        entry['external_run_id'] = run_id
    entry.update(extra)
    return entry


class _MergeGraphStub:
    """Routes the dup-merge's queries to canned rows, recording writes."""

    def __init__(
        self,
        releases: list[dict[str, typing.Any]],
        edges: dict[str, list[dict[str, typing.Any]]] | None = None,
        deployments_moved: int = 0,
        blockers_moved: int = 0,
        pointers_moved: int = 0,
    ) -> None:
        self.releases = releases
        #: release id -> rows of ``_RELEASE_EDGES``
        self.edges = edges or {}
        self.deployments_moved = deployments_moved
        self.blockers_moved = blockers_moved
        self.pointers_moved = pointers_moved
        self.calls: list[tuple[str, dict[str, typing.Any]]] = []

    def writes(self, marker: str) -> list[dict[str, typing.Any]]:
        return [params for query, params in self.calls if marker in query]

    async def execute(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        self.calls.append((query, params))
        if 'AS release' in query:
            return [{'release': props} for props in self.releases]
        if 'h:HAS_DEPLOYMENT' in query:
            return [{'id': f'd{i}'} for i in range(self.deployments_moved)]
        if 'h:BLOCKED_BY' in query:
            return [{'id': f'b{i}'} for i in range(self.blockers_moved)]
        if 'AS deployments' in query:
            return self.edges.get(str(params.get('release_id')), [])
        if 'MERGE (s)-[d:DEPLOYED_TO]->(e)' in query:
            return [{'id': params['survivor_id']}]
        if 'DEPLOYED_IN' in query:
            return [{'id': f'e{i}'} for i in range(self.pointers_moved)]
        if 'SET r.' in query:
            return [{'id': params['release_id']}]
        return []


class MergeDuplicateReleasesTests(unittest.IsolatedAsyncioTestCase):
    async def _merge(
        self,
        db: _MergeGraphStub,
        resolved: dict[str, str] | None,
        dry_run: bool = False,
    ) -> deployment_migration.DupMergeSummary:
        with mock.patch(
            _RESOLVE, mock.AsyncMock(return_value=resolved)
        ) as self.resolve:
            return await deployment_migration.merge_duplicate_releases(
                db, 'p1', org_slug='octo', dry_run=dry_run
            )

    async def test_no_duplicates_is_empty_and_never_asks_the_remote(
        self,
    ) -> None:
        db = _MergeGraphStub([_release('r1'), _release('r2', tag='2.0.0')])
        summary = await self._merge(db, {})
        self.assertEqual(0, summary.groups)
        self.resolve.assert_not_awaited()
        self.assertEqual(1, len(db.calls))

    async def test_tag_match_beats_newest(self) -> None:
        # r2 is newer, but r1's committish is what the tag points at.
        db = _MergeGraphStub(
            [
                _release('r1', committish='27f2f81'),
                _release(
                    'r2',
                    committish='3c1ea7b',
                    created_at='2026-02-01T00:00:00+00:00',
                ),
            ]
        )
        summary = await self._merge(db, {'1.0.0': '27f2f81abcdef012345'})
        self.assertEqual(1, summary.groups)
        self.assertEqual(1, summary.merged)
        self.assertEqual(0, summary.unresolved_tags)
        deleted = db.writes('DETACH DELETE r')
        self.assertEqual(['r2'], [w['release_id'] for w in deleted])

    async def test_promoted_committish_also_matches(self) -> None:
        db = _MergeGraphStub(
            [
                _release(
                    'r1', committish='fffffff', promoted_committish='27f2f81'
                ),
                _release(
                    'r2',
                    committish='eeeeeee',
                    created_at='2026-02-01T00:00:00+00:00',
                ),
            ]
        )
        await self._merge(db, {'1.0.0': '27f2f81abcdef012345'})
        deleted = db.writes('DETACH DELETE r')
        self.assertEqual(['r2'], [w['release_id'] for w in deleted])

    async def test_newest_survives_when_the_remote_cannot_answer(
        self,
    ) -> None:
        db = _MergeGraphStub(
            [
                _release('r1'),
                _release('r2', created_at='2026-02-01T00:00:00+00:00'),
            ]
        )
        summary = await self._merge(db, None)
        self.assertEqual(1, summary.unresolved_tags)
        deleted = db.writes('DETACH DELETE r')
        self.assertEqual(['r1'], [w['release_id'] for w in deleted])

    async def test_absent_and_error_answers_fall_back_to_newest(
        self,
    ) -> None:
        db = _MergeGraphStub(
            [
                _release('r1'),
                _release('r2', created_at='2026-02-01T00:00:00+00:00'),
            ]
        )
        summary = await self._merge(db, {'1.0.0': 'absent'})
        self.assertEqual(1, summary.unresolved_tags)
        self.assertEqual(
            ['r1'],
            [w['release_id'] for w in db.writes('DETACH DELETE r')],
        )

    async def test_edges_and_pointers_move_to_the_survivor(self) -> None:
        db = _MergeGraphStub(
            [
                _release('r1'),
                _release('r2', created_at='2026-02-01T00:00:00+00:00'),
            ],
            deployments_moved=2,
            blockers_moved=1,
            pointers_moved=1,
        )
        summary = await self._merge(db, None)
        self.assertEqual(2, summary.repointed_deployments)
        self.assertEqual(1, summary.repointed_blockers)
        self.assertEqual(1, summary.pointer_updates)
        repointed = db.writes('h:HAS_DEPLOYMENT')
        self.assertEqual('r1', repointed[0]['loser_id'])
        self.assertEqual('r2', repointed[0]['survivor_id'])

    async def test_deployment_arrays_union_onto_the_survivor_edge(
        self,
    ) -> None:
        shared = _event('2026-01-02T00:00:00+00:00')
        older = _event('2026-01-01T00:00:00+00:00', status='in_progress')
        db = _MergeGraphStub(
            [
                _release('r1'),
                _release('r2', created_at='2026-02-01T00:00:00+00:00'),
            ],
            edges={
                'r2': [
                    {
                        'env_slug': 'production',
                        'org_slug': 'octo',
                        'deployments': json.dumps([shared]),
                    }
                ],
                'r1': [
                    {
                        'env_slug': 'production',
                        'org_slug': 'octo',
                        'deployments': json.dumps([older, shared]),
                    }
                ],
            },
        )
        await self._merge(db, None)
        writes = db.writes('MERGE (s)-[d:DEPLOYED_TO]->(e)')
        self.assertEqual(1, len(writes))
        merged = json.loads(writes[0]['deployments'])
        # The shared entry dedupes; the loser's extra entry sorts first.
        self.assertEqual([older, shared], merged)
        self.assertEqual('production', writes[0]['env_slug'])
        self.assertEqual('octo', writes[0]['org_slug'])

    async def test_properties_fill_but_never_clobber(self) -> None:
        db = _MergeGraphStub(
            [
                _release('r1', description='real notes', title='kept'),
                _release(
                    'r2',
                    created_at='2026-02-01T00:00:00+00:00',
                    title='mine',
                ),
            ]
        )
        await self._merge(db, None)
        fills = db.writes('SET r.')
        self.assertEqual(1, len(fills))
        # The survivor (r2) lacks a description; the fold-in has one.
        self.assertEqual('real notes', fills[0]['description'])
        self.assertNotIn('title', fills[0])
        query = next(q for q, _ in db.calls if 'SET r.' in q)
        # The write re-checks emptiness so a concurrent fill survives.
        self.assertIn("CASE WHEN COALESCE(r.description, '') = ''", query)

    async def test_dry_run_reads_but_never_writes(self) -> None:
        db = _MergeGraphStub(
            [
                _release('r1', description='real notes'),
                _release('r2', created_at='2026-02-01T00:00:00+00:00'),
            ]
        )
        summary = await self._merge(db, None, dry_run=True)
        self.assertEqual(1, summary.groups)
        self.assertEqual(1, summary.merged)
        self.assertEqual(1, summary.filled_properties)
        self.assertEqual(1, len(db.calls))  # the read alone


class _MigrationGraphStub:
    """Routes the migration's queries, recording writes."""

    def __init__(
        self,
        edges: list[dict[str, typing.Any]],
        existing_run_ids: set[str] | None = None,
        prior_created: dict[str, str] | None = None,
    ) -> None:
        self.rows = edges
        self.existing_run_ids = existing_run_ids or set()
        #: run id -> created_at to report the node as pre-existing.
        self.prior_created = prior_created or {}
        self.calls: list[tuple[str, dict[str, typing.Any]]] = []

    def writes(self, marker: str) -> list[dict[str, typing.Any]]:
        return [params for query, params in self.calls if marker in query]

    async def execute(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        self.calls.append((query, params))
        if 'WHERE d.deployments IS NOT NULL' in query:
            return self.rows
        if 'd.external_run_id IN' in query:
            wanted = typing.cast('list[str]', params['run_ids'])
            return [
                {'run_id': run_id}
                for run_id in wanted
                if run_id in self.existing_run_ids
            ]
        if 'external_run_id: {external_run_id}' in query:
            run_id = str(params['external_run_id'])
            return [
                {
                    'id': f'node-{run_id}',
                    'prior_created': self.prior_created.get(run_id),
                }
            ]
        if 'MERGE (p)<-[:BELONGS_TO]-(d:Deployment {{id: {id}}})' in query:
            return [{'id': params['id'], 'prior_created': None}]
        if 'targets = 0' in query:
            return [{'id': params['deployment_id']}]
        if 'migrated_at' in query:
            return [{'slug': params['env_slug']}]
        return []


def _edge_row(
    release_id: str = 'r1',
    env_slug: str = 'production',
    entries: list[dict[str, typing.Any]] | None = None,
    tag: str | None = '1.0.0',
) -> dict[str, typing.Any]:
    return {
        'release_id': release_id,
        'tag': tag,
        'committish': 'aaaaaaa',
        'env_slug': env_slug,
        'org_slug': 'octo',
        'deployments': json.dumps(entries or []),
    }


class MigrateDeploymentArraysTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_edges_is_empty(self) -> None:
        db = _MigrationGraphStub([])
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1'
        )
        self.assertEqual(deployment_migration.MigrationSummary(), summary)

    async def test_entries_sharing_a_run_id_collapse_across_edges(
        self,
    ) -> None:
        # The 71 cross-linked stuck edges: the same run recorded pending
        # on one release and terminal on another.
        db = _MigrationGraphStub(
            [
                _edge_row(
                    'r1',
                    entries=[
                        _event(
                            '2026-01-01T00:00:00+00:00',
                            status='pending',
                            run_id='42',
                        )
                    ],
                ),
                _edge_row(
                    'r2',
                    entries=[
                        _event(
                            '2026-01-01T00:10:00+00:00',
                            status='success',
                            run_id='42',
                        )
                    ],
                ),
            ]
        )
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1'
        )
        writes = db.writes('external_run_id: {external_run_id}')
        self.assertEqual(1, len(writes))
        self.assertEqual('success', writes[0]['status'])
        self.assertEqual(
            ['pending', 'success'],
            [t['status'] for t in writes[0]['history']],
        )
        self.assertEqual('2026-01-01T00:00:00+00:00', writes[0]['first_ts'])
        self.assertEqual('2026-01-01T00:10:00+00:00', writes[0]['last_ts'])
        # The node attaches to the release that held the final entry.
        attach = db.writes('targets = 0')
        self.assertEqual('r2', attach[0]['release_id'])
        self.assertEqual(1, summary.created)
        self.assertEqual(2, summary.cleared_edges)

    async def test_consecutive_same_status_entries_collapse_in_history(
        self,
    ) -> None:
        db = _MigrationGraphStub(
            [
                _edge_row(
                    entries=[
                        _event(
                            '2026-01-01T00:00:00+00:00',
                            status='pending',
                            run_id='42',
                        ),
                        _event(
                            '2026-01-01T00:01:00+00:00',
                            status='pending',
                            run_id='42',
                        ),
                        _event(
                            '2026-01-01T00:02:00+00:00',
                            status='success',
                            run_id='42',
                        ),
                    ]
                )
            ]
        )
        await deployment_migration.migrate_deployment_arrays(db, 'p1')
        history = db.writes('external_run_id: {external_run_id}')[0]['history']
        self.assertEqual(
            ['pending', 'success'], [t['status'] for t in history]
        )
        self.assertEqual('2026-01-01T00:00:00+00:00', history[0]['timestamp'])

    async def test_an_existing_node_is_left_authoritative(self) -> None:
        db = _MigrationGraphStub(
            [
                _edge_row(
                    entries=[
                        _event(
                            '2026-01-01T00:00:00+00:00',
                            status='pending',
                            run_id='42',
                        )
                    ]
                )
            ],
            existing_run_ids={'42'},
            prior_created={'42': '2026-01-01T00:05:00+00:00'},
        )
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1'
        )
        self.assertEqual(0, summary.created)
        self.assertEqual(1, summary.existing)
        # The write still runs (COALESCE fills gaps), guarded in Cypher.
        query = next(
            q for q, _ in db.calls if 'external_run_id: {external_run_id}' in q
        )
        self.assertIn(
            'CASE WHEN prior_created IS NULL\n        THEN {status}', query
        )
        # The edge is still cleared: the node represents the run.
        self.assertEqual(1, summary.cleared_edges)

    async def test_entries_without_a_run_id_get_deterministic_nodes(
        self,
    ) -> None:
        entry = _event('2026-01-01T00:00:00+00:00')
        db = _MigrationGraphStub([_edge_row(entries=[entry])])
        await deployment_migration.migrate_deployment_arrays(db, 'p1')
        writes = db.writes('(d:Deployment {{id: {id}}})')
        self.assertEqual(1, len(writes))
        first_id = writes[0]['id']
        self.assertTrue(str(first_id).startswith('mig'))
        # A second run over the same data converges on the same id.
        db2 = _MigrationGraphStub([_edge_row(entries=[entry])])
        await deployment_migration.migrate_deployment_arrays(db2, 'p1')
        self.assertEqual(
            first_id, db2.writes('(d:Deployment {{id: {id}}})')[0]['id']
        )

    async def test_malformed_entries_are_preserved_on_the_edge(
        self,
    ) -> None:
        bad = {'status': 'nonsense'}
        db = _MigrationGraphStub(
            [
                _edge_row(
                    entries=[
                        _event('2026-01-01T00:00:00+00:00'),
                        bad,
                    ]
                )
            ]
        )
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1'
        )
        self.assertEqual(1, summary.malformed)
        self.assertEqual(1, summary.entries)
        self.assertEqual(1, summary.created)
        # A real run must not destroy what it could not validate: the
        # malformed entries ride along on the cleared edge.
        clears = db.writes('migrated_at')
        self.assertEqual(1, len(clears))
        self.assertEqual([bad], json.loads(clears[0]['skipped']))
        query = next(q for q, _ in db.calls if 'migrated_at' in q)
        self.assertIn('d.migration_skipped = {skipped}', query)
        self.assertEqual(2, clears[0]['count'])

    async def test_clean_edges_clear_without_a_skipped_stash(self) -> None:
        db = _MigrationGraphStub(
            [_edge_row(entries=[_event('2026-01-01T00:00:00+00:00')])]
        )
        await deployment_migration.migrate_deployment_arrays(db, 'p1')
        clears = db.writes('migrated_at')
        self.assertNotIn('skipped', clears[0])
        query = next(q for q, _ in db.calls if 'migrated_at' in q)
        self.assertNotIn('migration_skipped', query)

    async def test_edges_clear_with_an_audit_stamp(self) -> None:
        db = _MigrationGraphStub(
            [_edge_row(entries=[_event('2026-01-01T00:00:00+00:00')])]
        )
        await deployment_migration.migrate_deployment_arrays(db, 'p1')
        clears = db.writes('migrated_at')
        self.assertEqual(1, len(clears))
        self.assertEqual(1, clears[0]['count'])
        query = next(q for q, _ in db.calls if 'migrated_at' in q)
        self.assertIn('SET d.deployments = NULL', query)

    async def test_dry_run_reads_but_never_writes(self) -> None:
        db = _MigrationGraphStub(
            [
                _edge_row(
                    entries=[
                        _event('2026-01-01T00:00:00+00:00', run_id='42'),
                        _event('2026-01-02T00:00:00+00:00'),
                    ]
                )
            ],
            existing_run_ids={'42'},
        )
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1', dry_run=True
        )
        self.assertEqual(1, summary.edges)
        self.assertEqual(2, summary.entries)
        self.assertEqual(1, summary.existing)
        self.assertEqual(1, summary.created)  # the run-less entry alone
        self.assertEqual(0, summary.cleared_edges)
        self.assertEqual(2, len(db.calls))  # the two reads alone

    async def test_dry_run_counts_identical_runless_entries_once(
        self,
    ) -> None:
        entry = _event('2026-01-01T00:00:00+00:00')
        db = _MigrationGraphStub([_edge_row(entries=[entry, entry])])
        summary = await deployment_migration.migrate_deployment_arrays(
            db, 'p1', dry_run=True
        )
        # Both entries hash to one deterministic id, so one node.
        self.assertEqual(1, summary.created)


class _OrphanGraphStub:
    """Routes the orphan check's queries, recording deletes."""

    def __init__(
        self,
        usage: list[dict[str, typing.Any]],
        blockers: dict[str, list[str]] | None = None,
        delete_declined: bool = False,
    ) -> None:
        self.usage = usage
        self.blockers = blockers or {}
        #: Simulate the delete's re-check declining: the release gained
        #: history between the read and the write.
        self.delete_declined = delete_declined
        self.calls: list[tuple[str, dict[str, typing.Any]]] = []

    def writes(self, marker: str) -> list[dict[str, typing.Any]]:
        return [params for query, params in self.calls if marker in query]

    async def execute(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        self.calls.append((query, params))
        if 'r.workflow_run_id AS run_id' in query:
            return self.usage
        if 'RETURN b.id AS id' in query:
            return [
                {'id': blocker_id}
                for blocker_id in self.blockers.get(
                    str(params['release_id']), []
                )
            ]
        if 'DETACH DELETE r' in query:
            if self.delete_declined:
                return []
            return [{'rid': params['release_id']}]
        return []


def _usage_row(
    node_id: str,
    tag: str = '1.0.0',
    run_id: str | None = None,
    edges: int = 0,
    nodes: int = 0,
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'tag': tag,
        'run_id': run_id,
        'edges': edges,
        'nodes': nodes,
    }


class PurgeOrphanReleasesTests(unittest.IsolatedAsyncioTestCase):
    async def _purge(
        self,
        db: _OrphanGraphStub,
        resolved: dict[str, str] | None,
        dry_run: bool = False,
    ) -> deployment_migration.OrphanSummary | None:
        with mock.patch(
            _RESOLVE, mock.AsyncMock(return_value=resolved)
        ) as self.resolve:
            return await deployment_migration.purge_orphan_releases(
                db, 'p1', org_slug='octo', dry_run=dry_run
            )

    async def test_no_candidates_never_asks_the_remote(self) -> None:
        db = _OrphanGraphStub(
            [
                _usage_row('r1', run_id='42'),
                _usage_row('r2', edges=1),
                _usage_row('r3', nodes=1),
            ]
        )
        summary = await self._purge(db, {})
        assert summary is not None
        self.assertEqual(3, summary.tagged)
        self.assertEqual(0, summary.candidates)
        self.resolve.assert_not_awaited()

    async def test_unanswerable_integration_returns_none(self) -> None:
        db = _OrphanGraphStub([_usage_row('r1')])
        summary = await self._purge(db, None)
        self.assertIsNone(summary)
        # The lookup probes the repo before trusting per-tag 404s.
        self.assertTrue(self.resolve.await_args.kwargs['probe'])

    async def test_a_confirmed_absent_tag_deletes_the_release(self) -> None:
        db = _OrphanGraphStub(
            [_usage_row('r1')], blockers={'r1': ['b1', 'b2']}
        )
        summary = await self._purge(db, {'1.0.0': 'absent'})
        assert summary is not None
        self.assertEqual(1, summary.orphans)
        self.assertEqual(1, summary.deleted)
        self.assertEqual(2, summary.blockers_deleted)
        blocker_deletes = db.writes('DETACH DELETE b')
        self.assertEqual(1, len(blocker_deletes))
        self.assertEqual(['b1', 'b2'], blocker_deletes[0]['blocker_ids'])
        deletes = db.writes('DETACH DELETE r')
        self.assertEqual(1, len(deletes))
        self.assertEqual('1.0.0', deletes[0]['tag'])
        # The delete re-checks every orphan criterion and reports back.
        query = next(q for q, _ in db.calls if 'DETACH DELETE r' in q)
        self.assertIn("COALESCE(r.workflow_run_id, '') = ''", query)
        self.assertIn('WHERE edges = 0 AND nodes = 0', query)
        self.assertIn('RETURN rid', query)
        # The blockers come off only after the release delete happened.
        order = [q for q, _ in db.calls if 'DETACH DELETE' in q]
        self.assertIn('DETACH DELETE r', order[0])
        self.assertIn('DETACH DELETE b', order[1])

    async def test_a_declined_recheck_keeps_release_and_blockers(
        self,
    ) -> None:
        # The candidate gained a run id (or a deployment) between the
        # read and the delete: the re-check declines, and the blockers
        # must survive with the release they belong to.
        db = _OrphanGraphStub(
            [_usage_row('r1')],
            blockers={'r1': ['b1']},
            delete_declined=True,
        )
        summary = await self._purge(db, {'1.0.0': 'absent'})
        assert summary is not None
        self.assertEqual(1, summary.orphans)
        self.assertEqual(0, summary.deleted)
        self.assertEqual(0, summary.blockers_deleted)
        self.assertEqual([], db.writes('DETACH DELETE b'))

    async def test_an_existing_tag_is_not_an_orphan(self) -> None:
        db = _OrphanGraphStub([_usage_row('r1')])
        summary = await self._purge(db, {'1.0.0': 'abcdef1234567'})
        assert summary is not None
        self.assertEqual(0, summary.orphans)
        self.assertEqual([], db.writes('DETACH DELETE'))

    async def test_a_failed_lookup_never_reads_as_absence(self) -> None:
        db = _OrphanGraphStub([_usage_row('r1')])
        summary = await self._purge(db, {'1.0.0': 'error'})
        assert summary is not None
        self.assertEqual(1, summary.unresolved)
        self.assertEqual(0, summary.deleted)
        self.assertEqual([], db.writes('DETACH DELETE'))

    async def test_dry_run_reports_but_never_deletes(self) -> None:
        db = _OrphanGraphStub([_usage_row('r1')], blockers={'r1': ['b1']})
        summary = await self._purge(db, {'1.0.0': 'absent'}, dry_run=True)
        assert summary is not None
        self.assertEqual(1, summary.orphans)
        self.assertEqual(0, summary.deleted)
        self.assertEqual(0, summary.blockers_deleted)
        self.assertEqual([], db.writes('DETACH DELETE'))
