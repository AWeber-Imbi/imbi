"""Tests for ``Deployment`` node reads and writes.

These run against the live graph: the upsert leans on AGE-specific
behaviour (``MERGE`` on a path, list concatenation, ``WITH`` capturing
the pre-``SET`` state in place of ``ON CREATE SET``) that a mocked
connection would not exercise.

"""

import datetime
import typing
import unittest

import dotenv

from imbi.common import deployments, graph

dotenv.load_dotenv()

ORG = 'test-deployments-org'
PROJECT_ID = 'test-deployments-project'
RELEASE_ID = 'test-deployments-release'
OTHER_RELEASE_ID = 'test-deployments-release-2'
ENV = 'test-deployments-env'
OTHER_ENV = 'test-deployments-env-2'
NOW = datetime.datetime(2026, 8, 18, tzinfo=datetime.UTC)


class DeploymentNodeTestCase(unittest.IsolatedAsyncioTestCase):
    """Fixtures for one project, environment, and release."""

    async def asyncSetUp(self) -> None:
        self.graph = graph.Graph()
        await self.graph.open()
        await self._cleanup()
        await self.graph.execute(
            """
            MERGE (o:Organization {{slug: {org}}})
            MERGE (p:Project {{id: {project_id}}})
            MERGE (e:Environment {{slug: {env}}})
            MERGE (e)-[:BELONGS_TO]->(o)
            MERGE (r:Release {{id: {release_id}}})
            MERGE (p)-[:HAS_RELEASE]->(r)
            RETURN p.id AS id
            """,
            {
                'org': ORG,
                'project_id': PROJECT_ID,
                'env': ENV,
                'release_id': RELEASE_ID,
            },
            ['id'],
        )

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self.graph.close()

    async def _cleanup(self) -> None:
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project_id}}})
            OPTIONAL MATCH (p)<-[:BELONGS_TO]-(d:Deployment)
            DETACH DELETE d
            RETURN 1 AS ok
            """,
            {'project_id': PROJECT_ID},
            ['ok'],
        )
        for label, key, value in (
            ('Project', 'id', PROJECT_ID),
            ('Release', 'id', RELEASE_ID),
            ('Release', 'id', OTHER_RELEASE_ID),
            ('Environment', 'slug', ENV),
            ('Environment', 'slug', OTHER_ENV),
            ('Organization', 'slug', ORG),
        ):
            await self.graph.execute(
                f'MATCH (n:{label} {{{{{key}: {{value}}}}}}) '
                'DETACH DELETE n RETURN 1 AS ok',
                {'value': value},
                ['ok'],
            )

    async def upsert(
        self, **overrides: typing.Any
    ) -> deployments.UpsertResult | None:
        kwargs: dict[str, typing.Any] = {
            'org_slug': ORG,
            'project_id': PROJECT_ID,
            'env_slug': ENV,
            'release_id': RELEASE_ID,
            'status': 'in_progress',
            'external_run_id': '4242',
        }
        kwargs.update(overrides)
        return await deployments.upsert_deployment(self.graph, **kwargs)

    async def add_release(self, release_id: str) -> None:
        """Attach a second ``Release`` to the fixture project.

        ``asyncSetUp`` creates only ``RELEASE_ID``, and
        ``upsert_deployment`` MATCHes the named release -- so an upsert
        against an uncreated one writes nothing and returns ``None``
        rather than failing loudly.
        """
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project_id}}})
            MERGE (r:Release {{id: {release_id}}})
            MERGE (p)-[:HAS_RELEASE]->(r)
            RETURN r.id AS id
            """,
            {'project_id': PROJECT_ID, 'release_id': release_id},
            ['id'],
        )

    async def nodes(self) -> list[dict[str, typing.Any]]:
        rows = await self.graph.execute(
            """
            MATCH (:Project {{id: {project_id}}})
                  <-[:BELONGS_TO]-(d:Deployment)
            RETURN d AS deployment
            """,
            {'project_id': PROJECT_ID},
            ['deployment'],
        )
        return [graph.parse_agtype(row['deployment']) for row in rows]


class UpsertTests(DeploymentNodeTestCase):
    async def test_run_id_identity_is_idempotent(self) -> None:
        first = await self.upsert(status='in_progress')
        second = await self.upsert(status='success')
        assert first is not None
        assert second is not None
        self.assertEqual('created', first.outcome)
        self.assertEqual('updated', second.outcome)
        self.assertEqual(first.id, second.id)
        nodes = await self.nodes()
        self.assertEqual(1, len(nodes))
        self.assertEqual('success', nodes[0]['status'])
        self.assertEqual(
            ['in_progress', 'success'],
            [entry['status'] for entry in nodes[0]['history']],
        )

    async def test_replay_is_a_noop(self) -> None:
        first = await self.upsert(status='success', note='shipped')
        second = await self.upsert(status='success', note='shipped')
        assert first is not None
        assert second is not None
        self.assertEqual('created', first.outcome)
        self.assertEqual('noop', second.outcome)
        nodes = await self.nodes()
        self.assertEqual(1, len(nodes))
        self.assertEqual(1, len(nodes[0]['history']))

    async def test_null_run_url_does_not_clear_a_known_one(self) -> None:
        await self.upsert(
            status='in_progress', external_run_url='https://example/run'
        )
        await self.upsert(status='success', external_run_url=None)
        nodes = await self.nodes()
        self.assertEqual('https://example/run', nodes[0]['external_run_url'])

    async def test_without_run_id_every_call_creates_a_node(self) -> None:
        await self.upsert(external_run_id=None, status='in_progress')
        await self.upsert(external_run_id=None, status='success')
        self.assertEqual(2, len(await self.nodes()))

    async def test_environment_change_moves_the_deployment(self) -> None:
        """One run id means one deployment, in one environment.

        ``MERGE`` only ever adds an edge, so without deleting the stale
        one the node would target both environments and read back
        twice.
        """
        await self.graph.execute(
            """
            MATCH (o:Organization {{slug: {org}}})
            MERGE (e:Environment {{slug: {env}}})
            MERGE (e)-[:BELONGS_TO]->(o)
            RETURN e.slug AS slug
            """,
            {'org': ORG, 'env': OTHER_ENV},
            ['slug'],
        )
        first = await self.upsert(status='in_progress')
        second = await self.upsert(status='success', env_slug=OTHER_ENV)
        assert first is not None
        assert second is not None
        self.assertEqual(first.id, second.id)
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(OTHER_ENV, rows[0].environment['slug'])

    async def test_orphan_deployment_has_no_release(self) -> None:
        result = await self.upsert(release_id=None)
        assert result is not None
        by_project = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(by_project))
        self.assertIsNone(by_project[0].release)
        self.assertEqual(ENV, by_project[0].environment['slug'])
        self.assertEqual('in_progress', by_project[0].event.status)

    async def test_missing_environment_returns_none(self) -> None:
        self.assertIsNone(await self.upsert(env_slug='nope'))

    async def test_missing_release_returns_none(self) -> None:
        self.assertIsNone(await self.upsert(release_id='nope'))


class ReadTests(DeploymentNodeTestCase):
    async def test_node_renders_as_an_event(self) -> None:
        await self.upsert(
            status='success',
            note='via github',
            external_run_url='https://example/run',
            performed_by='alice@example.com',
        )
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        event = rows[0].event
        self.assertEqual('success', event.status)
        self.assertEqual('via github', event.note)
        self.assertEqual('4242', event.external_run_id)
        self.assertEqual('https://example/run', event.external_run_url)
        self.assertEqual('alice@example.com', event.performed_by)

    async def test_deployments_by_project_carries_release(self) -> None:
        await self.upsert(status='success')
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(RELEASE_ID, rows[0].release['id'])

    async def test_deployments_by_project_empty_without_ids(self) -> None:
        self.assertEqual(
            [], await deployments.deployments_by_project(self.graph, [])
        )

    async def _add_other_env(self) -> None:
        await self.graph.execute(
            """
            MATCH (o:Organization {{slug: {org}}})
            MERGE (e:Environment {{slug: {env}}})
            MERGE (e)-[:BELONGS_TO]->(o)
            RETURN e.slug AS slug
            """,
            {'org': ORG, 'env': OTHER_ENV},
            ['slug'],
        )

    async def test_latest_by_project_keeps_quiet_environments(self) -> None:
        """A busy environment must not crowd out a quiet one.

        The set-wide cap on :func:`deployments_by_project` is what made
        the projects list report staging and production as "not
        deployed": testing deploys far more often, so its rows filled
        the window and the older -- but still current -- staging and
        production rows fell outside it.
        """
        await self._add_other_env()
        await self.upsert(
            status='success',
            env_slug=OTHER_ENV,
            external_run_id=None,
            timestamp=NOW,
        )
        for offset in range(1, 4):
            await self.upsert(
                status='success',
                external_run_id=None,
                timestamp=NOW + datetime.timedelta(hours=offset),
            )

        capped = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID], limit=2
        )
        self.assertEqual({ENV}, {row.environment['slug'] for row in capped})

        rows = await deployments.latest_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(
            {ENV, OTHER_ENV}, {row.environment['slug'] for row in rows}
        )

    async def test_latest_by_project_is_newest_per_environment(self) -> None:
        await self.upsert(status='failed', external_run_id=None, timestamp=NOW)
        await self.upsert(
            status='success',
            external_run_id=None,
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        rows = await deployments.latest_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        self.assertEqual('success', rows[0].event.status)

    async def test_latest_by_project_breaks_timestamp_ties(self) -> None:
        """A tie must not leave the answer up to AGE's row order.

        Two rollouts can share an environment's newest timestamp, and
        every caller keeps the first row it sees for an environment, so
        an unresolved tie would let the current release and status
        change between two identical requests.
        """
        await self.upsert(status='failed', external_run_id=None, timestamp=NOW)
        await self.upsert(
            status='success', external_run_id=None, timestamp=NOW
        )
        nodes = await self.nodes()
        self.assertEqual(2, len(nodes))
        expected = max(nodes, key=lambda node: node['id'])
        for _ in range(2):
            rows = await deployments.latest_deployments_by_project(
                self.graph, [PROJECT_ID]
            )
            self.assertEqual(1, len(rows))
            self.assertEqual(expected['status'], rows[0].event.status)

    async def test_latest_by_project_breaks_release_fan_out(self) -> None:
        """Two releases on one node must not fan out into two rows.

        The ``OPTIONAL MATCH`` for the release multiplies a deployment
        carrying two ``HAS_DEPLOYMENT`` edges, and neither the
        timestamp nor the deployment id separates those rows -- they
        are the same node.  Unlike a timestamp tie this is not
        hypothetical: 37 projects' current deployments have two
        releases attached in production.
        """
        result = await self.upsert(status='success')
        assert result is not None
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project_id}}})
            MATCH (d:Deployment {{id: {deployment_id}}})
            MERGE (r:Release {{id: {release_id}}})
            MERGE (p)-[:HAS_RELEASE]->(r)
            MERGE (r)-[:HAS_DEPLOYMENT]->(d)
            RETURN r.id AS id
            """,
            {
                'project_id': PROJECT_ID,
                'deployment_id': result.id,
                'release_id': OTHER_RELEASE_ID,
            },
            ['id'],
        )
        expected = max(RELEASE_ID, OTHER_RELEASE_ID)
        for _ in range(2):
            rows = await deployments.latest_deployments_by_project(
                self.graph, [PROJECT_ID]
            )
            self.assertEqual(1, len(rows))
            assert rows[0].release is not None
            self.assertEqual(expected, rows[0].release['id'])

    async def test_latest_released_skips_a_newer_orphan(self) -> None:
        """A newer release-less node must not blank the environment.

        An orphan is a deployment whose tag could not be resolved to a
        Release, not evidence that nothing is deployed -- and it never
        heals, because ``attach_release`` runs only over aged in-flight
        runs.  Taking the newest node and then discarding it for having
        no release would leave the environment reading "not deployed"
        for good with a perfectly good release one row down.
        """
        await self.upsert(
            status='success', external_run_id=None, timestamp=NOW
        )
        await self.upsert(
            status='in_progress',
            release_id=None,
            external_run_id=None,
            timestamp=NOW + datetime.timedelta(hours=1),
        )

        # The unfiltered reader still answers with the true newest, which
        # is what scoring a deployment's status wants.
        newest = await deployments.latest_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(newest))
        self.assertIsNone(newest[0].release)
        self.assertEqual('in_progress', newest[0].event.status)

        rows = await deployments.latest_released_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(RELEASE_ID, rows[0].release['id'])
        self.assertEqual('success', rows[0].event.status)

    async def test_latest_released_ignores_a_newer_failed_close_out(
        self,
    ) -> None:
        """A superseded rollout's close-out must not win the pointer.

        The exact production shape: a release goes out and succeeds,
        a newer release supersedes it, and only then does the older
        deployment get closed out -- by the sweeper, from a remote
        status stamped when the *successor* went live.  That write is
        the newest one in the environment, so ranking on recency alone
        handed production back to the release it had already replaced.
        """
        await self.add_release(OTHER_RELEASE_ID)
        await self.upsert(
            status='success',
            release_id=OTHER_RELEASE_ID,
            external_run_id='newer-run',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        await self.upsert(
            status='failed',
            note='closed by sweeper: run cancelled',
            external_run_id='older-run',
            timestamp=NOW + datetime.timedelta(hours=2),
        )

        rows = await deployments.latest_released_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(OTHER_RELEASE_ID, rows[0].release['id'])
        self.assertEqual('success', rows[0].event.status)

    async def test_latest_released_ignores_a_newer_rolled_back(self) -> None:
        """``rolled_back`` says outright that it is not serving."""
        await self.add_release(OTHER_RELEASE_ID)
        await self.upsert(
            status='success',
            release_id=OTHER_RELEASE_ID,
            external_run_id='newer-run',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        await self.upsert(
            status='rolled_back',
            external_run_id='older-run',
            timestamp=NOW + datetime.timedelta(hours=2),
        )

        rows = await deployments.latest_released_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(OTHER_RELEASE_ID, rows[0].release['id'])

    async def test_latest_released_still_surfaces_a_rollout_in_flight(
        self,
    ) -> None:
        """Excluding failures must not also hide a live rollout.

        ``_hydrate_release_train`` selects ``pending``/``in_progress``
        events to poll and self-heal, so filtering the reader down to
        ``success`` would strand every in-flight deployment with the
        null ``external_run_url`` that pass exists to fill in.
        """
        await self.add_release(OTHER_RELEASE_ID)
        await self.upsert(
            status='success', external_run_id='older-run', timestamp=NOW
        )
        await self.upsert(
            status='in_progress',
            release_id=OTHER_RELEASE_ID,
            external_run_id='newer-run',
            timestamp=NOW + datetime.timedelta(hours=1),
        )

        rows = await deployments.latest_released_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(OTHER_RELEASE_ID, rows[0].release['id'])
        self.assertEqual('in_progress', rows[0].event.status)

    async def test_latest_released_empty_without_ids(self) -> None:
        self.assertEqual(
            [],
            await deployments.latest_released_deployments_by_project(
                self.graph, []
            ),
        )

    async def test_latest_by_project_carries_release(self) -> None:
        await self.upsert(status='success')
        rows = await deployments.latest_deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(RELEASE_ID, rows[0].release['id'])

    async def test_latest_by_project_empty_without_ids(self) -> None:
        self.assertEqual(
            [], await deployments.latest_deployments_by_project(self.graph, [])
        )


class CurrentAndLatestTests(DeploymentNodeTestCase):
    """The reader both "current release" surfaces derive from.

    Every case here is a row of the plan's test matrix: what the
    provider serves is the newest attempt whose *latest* status is
    success, and the newest attempt of any status is reported beside it
    rather than in place of it.
    """

    async def _add_release(self) -> None:
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project_id}}})
            MERGE (r:Release {{id: {release_id}}})
            MERGE (p)-[:HAS_RELEASE]->(r)
            RETURN r.id AS id
            """,
            {'project_id': PROJECT_ID, 'release_id': OTHER_RELEASE_ID},
            ['id'],
        )

    async def _state(self) -> deployments.EnvironmentReleaseState:
        rows = await deployments.current_and_latest_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        return rows[0]

    async def test_failed_attempt_does_not_displace_a_success(self) -> None:
        """Matrix 1: the newest attempt failed."""
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='failed',
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        state = await self._state()
        assert state.current is not None
        self.assertEqual('1', state.current.event.external_run_id)
        self.assertEqual('success', state.current.event.status)
        self.assertEqual('2', state.latest.event.external_run_id)
        self.assertEqual('failed', state.latest.event.status)

    async def test_pending_attempt_does_not_displace_a_success(self) -> None:
        """Matrix 2: the newest attempt is still in flight."""
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='pending',
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        state = await self._state()
        assert state.current is not None
        self.assertEqual('1', state.current.event.external_run_id)
        self.assertEqual('pending', state.latest.event.status)

    async def test_newer_success_takes_over(self) -> None:
        """Matrix 3: a success of B inactivates A."""
        await self._add_release()
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='success',
            release_id=OTHER_RELEASE_ID,
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        await self.upsert(
            status='rolled_back',
            external_run_id='1',
            timestamp=NOW + datetime.timedelta(hours=2),
        )
        state = await self._state()
        assert state.current is not None
        assert state.current.release is not None
        self.assertEqual(OTHER_RELEASE_ID, state.current.release['id'])
        self.assertEqual('rolled_back', state.latest.event.status)

    async def test_rollback_is_a_new_success_of_the_old_release(self) -> None:
        """Matrix 4: rolling back means deploying A again."""
        await self._add_release()
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='success',
            release_id=OTHER_RELEASE_ID,
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        await self.upsert(
            status='success',
            external_run_id='3',
            timestamp=NOW + datetime.timedelta(hours=2),
        )
        state = await self._state()
        assert state.current is not None
        assert state.current.release is not None
        self.assertEqual(RELEASE_ID, state.current.release['id'])
        self.assertEqual(state.current, state.latest)

    async def test_late_inactive_does_not_demote_a_newer_attempt(
        self,
    ) -> None:
        """Matrix 5: an old attempt of A goes inactive after a newer one."""
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='success',
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        await self.upsert(
            status='rolled_back',
            external_run_id='1',
            timestamp=NOW + datetime.timedelta(hours=2),
        )
        state = await self._state()
        assert state.current is not None
        assert state.current.release is not None
        self.assertEqual('2', state.current.event.external_run_id)
        self.assertEqual(RELEASE_ID, state.current.release['id'])

    async def test_one_release_deployed_twice_is_stable(self) -> None:
        """Matrix 6: two attempts, one release, current unchanged."""
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='success',
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        self.assertEqual(2, len(await self.nodes()))
        state = await self._state()
        assert state.current is not None
        assert state.current.release is not None
        self.assertEqual(RELEASE_ID, state.current.release['id'])
        self.assertEqual(state.current, state.latest)

    async def test_newest_of_two_active_deployments_wins(self) -> None:
        """Matrix 11: the provider left both deployments active.

        Imbi's policy is the newest attempt whose latest status is
        success, whatever else the provider still calls active.
        """
        await self._add_release()
        await self.upsert(status='success', external_run_id='1', timestamp=NOW)
        await self.upsert(
            status='success',
            release_id=OTHER_RELEASE_ID,
            external_run_id='2',
            timestamp=NOW + datetime.timedelta(hours=1),
        )
        state = await self._state()
        assert state.current is not None
        assert state.current.release is not None
        self.assertEqual(OTHER_RELEASE_ID, state.current.release['id'])
        self.assertEqual(state.current, state.latest)

    async def test_no_success_leaves_current_unset(self) -> None:
        await self.upsert(status='failed', external_run_id='1', timestamp=NOW)
        state = await self._state()
        self.assertIsNone(state.current)
        self.assertEqual('failed', state.latest.event.status)

    async def test_empty_without_ids(self) -> None:
        self.assertEqual(
            [], await deployments.current_and_latest_by_project(self.graph, [])
        )


class LifecycleTests(DeploymentNodeTestCase):
    async def test_close_in_flight_marks_terminal(self) -> None:
        await self.upsert(status='in_progress')
        closed = await deployments.close_in_flight(
            self.graph,
            project_id=PROJECT_ID,
            release_id=RELEASE_ID,
            env_slug=ENV,
            status='failed',
            note='promote abandoned',
            source='promote-queue',
        )
        self.assertEqual(1, len(closed))
        node = (await self.nodes())[0]
        self.assertEqual('failed', node['status'])
        self.assertEqual('promote abandoned', node['note'])
        self.assertEqual(
            ['in_progress', 'failed'],
            [entry['status'] for entry in node['history']],
        )

    async def test_close_in_flight_leaves_terminal_alone(self) -> None:
        await self.upsert(status='success')
        closed = await deployments.close_in_flight(
            self.graph,
            project_id=PROJECT_ID,
            release_id=RELEASE_ID,
            env_slug=ENV,
            status='failed',
        )
        self.assertEqual([], closed)
        self.assertEqual('success', (await self.nodes())[0]['status'])

    async def test_stuck_selects_only_aged_in_flight_runs(self) -> None:
        old = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        await self.upsert(status='in_progress', timestamp=old)
        await self.upsert(
            status='in_progress', external_run_id='fresh', timestamp=NOW
        )
        await self.upsert(
            status='success', external_run_id='done', timestamp=old
        )
        await self.upsert(
            status='in_progress', external_run_id=None, timestamp=old
        )
        stuck = await deployments.stuck_deployments(
            self.graph,
            project_id=PROJECT_ID,
            cutoff=datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC),
        )
        self.assertEqual(1, len(stuck))
        self.assertEqual('4242', stuck[0].external_run_id)
        self.assertEqual(RELEASE_ID, stuck[0].release_id)
        self.assertEqual(ENV, stuck[0].env_slug)
        self.assertEqual(ORG, stuck[0].org_slug)

    async def test_stuck_reports_an_unattached_deployment(self) -> None:
        old = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        await self.upsert(
            status='in_progress',
            release_id=None,
            release_tag='1.2.3',
            release_committish='abc1234',
            timestamp=old,
        )
        stuck = await deployments.stuck_deployments(
            self.graph,
            project_id=PROJECT_ID,
            cutoff=NOW,
        )
        self.assertEqual(1, len(stuck))
        self.assertIsNone(stuck[0].release_id)
        self.assertEqual('1.2.3', stuck[0].release_tag)
        self.assertEqual('abc1234', stuck[0].release_committish)

    async def test_attach_release(self) -> None:
        result = await self.upsert(release_id=None)
        assert result is not None
        self.assertTrue(
            await deployments.attach_release(
                self.graph,
                project_id=PROJECT_ID,
                deployment_id=result.id,
                release_id=RELEASE_ID,
            )
        )
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        assert rows[0].release is not None
        self.assertEqual(RELEASE_ID, rows[0].release['id'])

    async def test_attach_release_missing_release(self) -> None:
        result = await self.upsert(release_id=None)
        assert result is not None
        self.assertFalse(
            await deployments.attach_release(
                self.graph,
                project_id=PROJECT_ID,
                deployment_id=result.id,
                release_id='nope',
            )
        )


class OriginTests(DeploymentNodeTestCase):
    async def test_origin_records_the_creating_writer(self) -> None:
        await self.upsert(status='in_progress', source='promote')
        await self.upsert(status='success', source='gateway')
        node = (await self.nodes())[0]
        # Create-only: the webhook confirming a promote's rollout does
        # not make the deployment the webhook's.
        self.assertEqual('promote', node['origin'])
        self.assertEqual(
            ['promote', 'gateway'],
            [entry['source'] for entry in node['history']],
        )

    async def test_stuck_reports_the_origin(self) -> None:
        await self.upsert(
            status='in_progress',
            source='promote',
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
        stuck = await deployments.stuck_deployments(
            self.graph, project_id=PROJECT_ID, cutoff=NOW
        )
        self.assertEqual('promote', stuck[0].origin)


class MergeEventsTests(unittest.TestCase):
    def test_naive_legacy_timestamps_sort_alongside_node_ones(self) -> None:
        """A legacy entry written without an offset must not raise.

        The array stored whatever its writer produced; the node always
        stores aware UTC.  Comparing the two is a ``TypeError`` unless
        the naive one is read as UTC.
        """
        from imbi.common import models

        naive = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 1),  # noqa: DTZ001
            status='pending',
        )
        aware = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            status='success',
        )
        self.assertEqual(
            [naive, aware], deployments.merge_events([aware], [naive])
        )

    def test_one_run_in_both_shapes_collapses_to_the_newest(self) -> None:
        """A rollout can exist as an array entry and as a node.

        It started before the node cutover and a later webhook wrote it
        as a node; returning it twice would double-count one rollout.
        """
        from imbi.common import models

        legacy = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            status='in_progress',
            external_run_id='42',
        )
        node = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
            status='success',
            external_run_id='42',
        )
        other = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC),
            status='success',
        )
        self.assertEqual(
            [node, other], deployments.merge_events([legacy, other], [node])
        )

    def test_orders_by_timestamp(self) -> None:
        from imbi.common import models

        older = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            status='pending',
        )
        newer = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            status='success',
        )
        self.assertEqual(
            [older, newer], deployments.merge_events([newer], [older])
        )
