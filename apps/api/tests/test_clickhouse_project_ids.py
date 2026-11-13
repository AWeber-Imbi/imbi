"""Org-wide project-ID lists reach ClickHouse in one query (#593).

A bound ``Array(String)`` goes as one HTML form field, and ClickHouse
rejects a field longer than 131072 bytes -- about 5000 project IDs.
The ``project_ids`` external table goes as a file part instead.
"""

import datetime
import unittest
import uuid

from imbi.api import commit_pushed_at_repair, drift
from imbi.api.agent_tasks import log
from imbi.api.endpoints import project_deployments, projects
from imbi.common import clickhouse
from imbi.common.clickhouse import client
from imbi.plugins.github import commits


class ProjectIdsExternalTableTestCase(unittest.IsolatedAsyncioTestCase):
    """Runs against the test ClickHouse server."""

    async def asyncSetUp(self) -> None:
        # The client binds to the loop that opened it; take a private
        # instance and hand the old one back, as test_component_facts
        # does.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def test_more_ids_than_a_form_field_holds(self) -> None:
        ids = [f'project-{n:013d}' for n in range(10000)]
        self.assertGreater(len(str(ids)), 131072)
        rows = await clickhouse.query(
            'SELECT count() AS n FROM project_ids'
            ' WHERE project_id IN (SELECT project_id FROM project_ids)'
            ' AND {x:String} = {x:String}',
            {'x': 'a'},
            project_ids=ids,
        )
        self.assertEqual(rows, [{'n': 10000}])

    async def test_more_ids_than_a_form_field_holds_in_a_named_table(
        self,
    ) -> None:
        ids = [f'release-{n:013d}' for n in range(10000)]
        rows = await clickhouse.query(
            'SELECT count() AS n FROM release_ids'
            ' WHERE id IN (SELECT id FROM release_ids)',
            project_ids=['p1'],
            tables={'release_ids': ids},
        )
        self.assertEqual(rows, [{'n': 10000}])


class ProjectsCallersTestCase(unittest.IsolatedAsyncioTestCase):
    """The projects.py reads, with an org-sized ID list (#598).

    Each pads its real input with 10000 project IDs that match nothing.
    As bound arrays those went over the form-field limit, the query
    failed, and the caller swallowed the error into an empty result.
    """

    async def asyncSetUp(self) -> None:
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        self.pid = f'p598-{uuid.uuid4().hex}'
        self.filler = [f'filler-{n:013d}' for n in range(10000)]

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def _commit(self, sha: str, day: int, drift: bool | None) -> None:
        await clickhouse.command(
            'INSERT INTO imbi.commits (project_id, sha, ref, message,'
            ' authored_at, committed_at, pushed_at, recorded_at) VALUES'
            ' ({pid:String}, {sha:String}, {ref:String}, {msg:String},'
            ' {at:DateTime64(3)}, {at:DateTime64(3)}, {at:DateTime64(3)},'
            ' now64(3))',
            {
                'pid': self.pid,
                'sha': sha,
                'ref': 'main',
                'msg': '',
                'at': _at(day),
            },
        )
        if drift is not None:
            await clickhouse.command(
                'INSERT INTO imbi.commit_drift (project_id, sha,'
                ' drift_detected, paths, recorded_at) VALUES'
                ' ({pid:String}, {sha:String}, {d:Bool}, [], now64(3))',
                {'pid': self.pid, 'sha': sha, 'd': drift},
            )

    async def test_actionable_commit_times(self) -> None:
        await self._commit('a' * 40, 10, None)  # on the lower bound
        await self._commit('b' * 40, 15, True)
        await self._commit('c' * 40, 16, False)  # proven clean
        await self._commit('d' * 40, 25, None)  # after the window
        windows = dict.fromkeys(self.filler, (_at(1), _at(2)))
        windows[self.pid] = (_at(10), _at(20))
        result = await projects._fetch_actionable_commit_times(windows)
        self.assertEqual(
            {
                self.pid: [
                    projects.ActionableCommit('aaaaaaa', _at(10), _at(10)),
                    projects.ActionableCommit('bbbbbbb', _at(15), _at(15)),
                ]
            },
            {k: sorted(v) for k, v in (result or {}).items()},
        )

    async def test_commit_times(self) -> None:
        await self._commit('e' * 40, 12, None)
        result = await projects._fetch_commit_times(
            [*self.filler, self.pid],
            [f'{n:07d}' for n in range(20000)] + ['eeeeeee'],
        )
        self.assertEqual({(self.pid, 'eeeeeee'): _at(12)}, result)

    async def test_performed_by(self) -> None:
        await clickhouse.command(
            'INSERT INTO imbi.operations_log (id, occurred_at, recorded_at,'
            ' recorded_by, performed_by, project_id, project_slug,'
            ' environment_slug, entry_type, description, version) VALUES'
            " ({id:String}, now64(3), now64(3), 'test', 'alice',"
            " {pid:String}, 'p', 'prod', 'Deployed', '', '1.0.0')",
            {'id': uuid.uuid4().hex, 'pid': self.pid},
        )
        targets = [(pid, 'prod', '1.0.0', None) for pid in self.filler]
        result = await projects.lookup_ops_log_performed_by(
            [*targets, (self.pid, 'prod', '1.0.0', None)]
        )
        self.assertEqual({(self.pid, 'prod'): 'alice'}, result)


class OtherCallersTestCase(unittest.IsolatedAsyncioTestCase):
    """The other reads that took a list as a bound array (#664).

    A compare range answers up to 5000 commits and a task backlog grows
    with the organization; either is longer than one form field.  Each
    test pads its real input with IDs that match nothing.
    """

    async def asyncSetUp(self) -> None:
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        self.pid = f'p664-{uuid.uuid4().hex}'
        self.shas = [f'{n:040x}' for n in range(5000)]
        self.assertGreater(len(str(self.shas)), 131072)

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def test_verdicts_by_sha(self) -> None:
        sha = 'f' * 40
        await clickhouse.command(
            'INSERT INTO imbi.commit_drift (project_id, sha,'
            ' drift_detected, paths, recorded_at) VALUES'
            ' ({pid:String}, {sha:String}, true, [], now64(3))',
            {'pid': self.pid, 'sha': sha},
        )
        result = await drift.verdicts_by_sha(self.pid, [*self.shas, sha])
        self.assertEqual({sha: True}, result)

    async def test_tags_by_sha(self) -> None:
        sha = 'f' * 40
        await clickhouse.command(
            'INSERT INTO imbi.tags (project_id, name, sha, tagged_at,'
            ' recorded_at) VALUES ({pid:String}, {name:String},'
            ' {sha:String}, now64(3), now64(3))',
            {'pid': self.pid, 'name': 'v1.0.0', 'sha': sha},
        )
        result = await project_deployments._tags_by_sha(
            self.pid, [*self.shas, sha]
        )
        self.assertEqual({sha: 'v1.0.0'}, result)

    async def test_task_event_counts(self) -> None:
        org = f'o664-{uuid.uuid4().hex}'
        task_id = str(uuid.uuid4())
        await clickhouse.command(
            'INSERT INTO imbi.agent_task_events (organization_id,'
            ' task_id, seq) VALUES ({org:String}, {task:String}, 3)',
            {'org': org, 'task': task_id},
        )
        task_ids = [str(uuid.uuid4()) for _ in range(5000)] + [task_id]
        self.assertEqual(
            {task_id: (1, 3)}, await log.event_counts(org, task_ids)
        )
        self.assertEqual({}, await log.usage_counts(org, task_ids))

    async def _insert_commit(self, sha: str, pushed_at: str) -> None:
        await clickhouse.command(
            'INSERT INTO imbi.commits (project_id, sha, ref, message,'
            ' authored_at, pushed_at, recorded_at) VALUES ({pid:String},'
            " {sha:String}, 'main', 'm', now64(3),"
            ' {pushed:DateTime64(3)}, now64(3))',
            {'pid': self.pid, 'sha': sha, 'pushed': pushed_at},
        )

    async def test_stored_pushed_at(self) -> None:
        sha = 'f' * 40
        await self._insert_commit(sha, '2026-08-01 00:00:00')
        result = await commits._stored_pushed_at(self.pid, [*self.shas, sha])
        self.assertEqual({sha: _at(1)}, result)

    async def test_repair_commits_lookup(self) -> None:
        sha = 'f' * 40
        await self._insert_commit(sha, '2026-08-01 00:00:00')
        rows = await clickhouse.query(
            commit_pushed_at_repair._COMMITS_SQL,
            {'project_id': self.pid},
            tables={'shas': [*self.shas, sha]},
        )
        self.assertEqual([sha], [row['sha'] for row in rows])


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 8, day, tzinfo=datetime.UTC)
