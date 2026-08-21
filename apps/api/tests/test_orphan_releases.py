"""Tests for the orphan-release check and purge."""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from imbi.api import orphan_releases

_RESOLVE = 'imbi.api.endpoints.project_deployments.resolve_remote_tags'


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
    ) -> orphan_releases.OrphanSummary | None:
        with mock.patch(
            _RESOLVE, mock.AsyncMock(return_value=resolved)
        ) as self.resolve:
            return await orphan_releases.purge_orphan_releases(
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
