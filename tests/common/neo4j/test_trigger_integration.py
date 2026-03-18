"""Integration tests for APOC trigger: project/type slug uniqueness.

These tests require a live Neo4j instance with APOC installed and
apoc.trigger.enabled=true.  They are skipped when either condition
is not met, or when the trigger does not become active within the
poll timeout (APOC triggers propagate asynchronously).

The trigger enforces: for a given ProjectType, no two Projects can have
the same slug.  It fires in two scenarios:
  1. A new [:TYPE] relationship is created for a project whose slug is
     already held by another project linked to that same ProjectType.
  2. A Project.slug is updated to a value already used by another project
     linked to the same ProjectType.
"""

import asyncio
import unittest
import uuid

import neo4j as neo4j_lib

from imbi_common import settings
from imbi_common.neo4j import constants

# How long (seconds) to poll waiting for the trigger to become active
_TRIGGER_ACTIVE_TIMEOUT = 60


def _neo4j_url() -> str | None:
    try:
        return str(settings.Neo4j().url)
    except Exception:  # noqa: BLE001
        return None


@unittest.skipUnless(
    _neo4j_url(),
    'NEO4J_URL not configured',
)
class TriggerSlugUniquenessIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Regression tests for the project_type_slug_unique APOC trigger."""

    async def _install_triggers(self) -> bool:
        """Drop, reinstall, and sentinel-poll triggers.

        Returns True if APOC is available and the trigger is active.
        """
        async with self._driver.session(database='system') as session:
            for trigger in constants.TRIGGERS:
                try:
                    await session.run(
                        'CALL apoc.trigger.drop($db, $name)',
                        db=self._db,
                        name=trigger['name'],
                    )
                except neo4j_lib.exceptions.ClientError as err:
                    if 'ProcedureNotFound' in (err.code or ''):
                        return False
                    # Ignore "not found" — trigger may not exist yet

        # Wait for the old trigger to disappear before reinstalling
        for _ in range(15):
            async with self._driver.session(database=self._db) as s:
                r = await s.run(
                    'CALL apoc.trigger.list() YIELD name '
                    'WHERE name = $n RETURN name',
                    {'n': constants.TRIGGERS[0]['name']},
                )
                rows = await r.data()
                if not rows:
                    break
            await asyncio.sleep(1)

        async with self._driver.session(database='system') as session:
            for trigger in constants.TRIGGERS:
                try:
                    await session.run(
                        'CALL apoc.trigger.install('
                        '    $db, $name, $statement, $selector, $config'
                        ')',
                        db=self._db,
                        name=trigger['name'],
                        statement=trigger['query'],
                        selector=trigger['selector'],
                        config=trigger.get('config', {}),
                    )
                except neo4j_lib.exceptions.ClientError as err:
                    if 'ProcedureNotFound' in (err.code or ''):
                        return False
                    raise

        return await self._sentinel_poll()

    async def _sentinel_poll(self) -> bool:
        """Poll until the trigger demonstrably blocks a collision.

        APOC propagates triggers asynchronously; appearing in the list is
        not sufficient — we must confirm the trigger actually fires before
        proceeding with real test data.

        Returns True if the trigger became active within the timeout.
        """
        pt = f'__sentinel_pt_{uuid.uuid4().hex[:8]}__'
        pa = f'__sentinel_pa_{pt}__'

        async with self._driver.session(database=self._db) as s:
            await s.run(
                'CREATE (:ProjectType {slug:$pt}), '
                '(:Project {slug:$slug, name:"sa"}), '
                '(:Project {slug:$slug, name:"sb"})',
                {'pt': pt, 'slug': pa},
            )
            r = await s.run(
                'MATCH (p:Project {slug:$s, name:"sa"}), '
                '(pt:ProjectType {slug:$pt}) CREATE (p)-[:TYPE]->(pt)',
                {'s': pa, 'pt': pt},
            )
            await r.consume()

        active = False
        for _ in range(_TRIGGER_ACTIVE_TIMEOUT):
            async with self._driver.session(database=self._db) as s:
                try:
                    r = await s.run(
                        'MATCH (p:Project {slug:$s, name:"sb"}), '
                        '(pt:ProjectType {slug:$pt}) '
                        'CREATE (p)-[:TYPE]->(pt)',
                        {'s': pa, 'pt': pt},
                    )
                    await r.consume()
                except neo4j_lib.exceptions.ClientError as err:
                    if 'already exists' in str(err):
                        active = True
                        break
            await asyncio.sleep(1)

        async with self._driver.session(database=self._db) as s:
            await s.run(
                'MATCH (n) WHERE n.slug IN [$pt, $pa] DETACH DELETE n',
                {'pt': pt, 'pa': pa},
            )

        return active

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        cfg = settings.Neo4j()
        auth: tuple[str, str] | None = None
        if cfg.user and cfg.password:
            auth = (cfg.user, cfg.password)
        self._db = cfg.database
        self._driver = neo4j_lib.AsyncGraphDatabase.driver(
            str(cfg.url), auth=auth
        )

        # Drop any existing triggers then reinstall, so the execution engine
        # picks up the current query (install-only updates metadata but may
        # leave the old compiled query active until a drop+reinstall cycle).
        self._apoc_available = await self._install_triggers()
        if not self._apoc_available:
            return

        # Set up test data.
        #
        # We need three projects:
        #  - p1: slug=SHARED, linked to pt  → the "existing" record
        #  - p2: slug=SHARED (same), not linked  → used in test_new_rel
        #  - p3: slug=OTHER, not linked yet → used in test_slug_update
        suffix = uuid.uuid4().hex[:8]
        self._pt_slug = f'test-pt-{suffix}'
        self._shared_slug = f'proj-shared-{suffix}'  # collision slug
        self._p2_slug = f'proj-b-{suffix}'  # distinct slug

        async with self._driver.session(database=self._db) as session:
            await session.run(
                'CREATE (:ProjectType {slug: $s})', {'s': self._pt_slug}
            )
            # p1: has the shared slug, linked to type
            await session.run(
                'CREATE (:Project {slug: $s, name: $n})',
                {'s': self._shared_slug, 'n': f'Project 1 {suffix}'},
            )
            await session.run(
                'MATCH (p:Project {slug:$ps}), (pt:ProjectType {slug:$pts}) '
                'CREATE (p)-[:TYPE]->(pt)',
                {'ps': self._shared_slug, 'pts': self._pt_slug},
            )
            # p2: also has the shared slug, NOT linked yet
            await session.run(
                'CREATE (:Project {slug: $s, name: $n})',
                {'s': self._shared_slug, 'n': f'Project 2 {suffix}'},
            )
            # p3: distinct slug, NOT linked yet
            await session.run(
                'CREATE (:Project {slug: $s, name: $n})',
                {'s': self._p2_slug, 'n': f'Project 3 {suffix}'},
            )

    async def asyncTearDown(self) -> None:
        if hasattr(self, '_pt_slug'):
            async with self._driver.session(database=self._db) as session:
                await session.run(
                    'MATCH (n) WHERE n.slug IN $slugs DETACH DELETE n',
                    {
                        'slugs': [
                            self._pt_slug,
                            self._shared_slug,
                            self._p2_slug,
                        ]
                    },
                )
        await self._driver.close()
        await super().asyncTearDown()

    async def test_new_relationship_collision_blocked(self) -> None:
        """Trigger blocks linking a project whose slug is already used by
        another project linked to the same ProjectType."""
        if not self._apoc_available:
            self.skipTest('APOC trigger not available')

        # p2 has the same slug as p1 which is already linked to pt.
        # Creating this [:TYPE] relationship must be blocked.
        async with self._driver.session(database=self._db) as session:
            with self.assertRaises(neo4j_lib.exceptions.ClientError) as cm:
                # There are two Project nodes with slug=shared_slug;
                # LIMIT 1 picks p2 (p1 already has the rel, the trigger
                # fires on the newly created rel and finds p1 as a dup).
                r = await session.run(
                    'MATCH (p:Project {slug: $ps})-[:TYPE]->(pt:ProjectType) '
                    'WITH pt '
                    'MATCH (p2:Project {slug: $ps}) '
                    'WHERE NOT (p2)-[:TYPE]->() '
                    'WITH p2, pt LIMIT 1 '
                    'CREATE (p2)-[:TYPE]->(pt)',
                    {'ps': self._shared_slug},
                )
                await r.consume()
        self.assertIn('already exists', str(cm.exception))
        self.assertIn(self._shared_slug, str(cm.exception))

    async def test_slug_update_collision_blocked(self) -> None:
        """Trigger blocks updating a Project slug to collide with an existing
        (Project.slug, ProjectType) pair."""
        if not self._apoc_available:
            self.skipTest('APOC trigger not available')

        # Give p3 (distinct slug) its own TYPE relationship
        async with self._driver.session(database=self._db) as session:
            r = await session.run(
                'MATCH (p:Project {slug: $ps}), (pt:ProjectType {slug: $pts}) '
                'CREATE (p)-[:TYPE]->(pt)',
                {'ps': self._p2_slug, 'pts': self._pt_slug},
            )
            await r.consume()

        # Rename p3's slug to collide with p1 — trigger must block
        async with self._driver.session(database=self._db) as session:
            with self.assertRaises(neo4j_lib.exceptions.ClientError) as cm:
                r = await session.run(
                    'MATCH (p:Project {slug: $old}) SET p.slug = $new',
                    {'old': self._p2_slug, 'new': self._shared_slug},
                )
                await r.consume()
        self.assertIn('already exists', str(cm.exception))
        self.assertIn(self._shared_slug, str(cm.exception))
