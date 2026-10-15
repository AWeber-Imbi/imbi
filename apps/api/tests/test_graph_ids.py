"""Ids for organizations and users made before nodes had an id."""

import fastapi

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import graph_ids
from imbi.api.auth import organizations, permissions


class GraphIdsTestCase(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.legacy = f'legacy-{self.org}'
        self.legacy_user = f'legacy-{self.org}@example.com'
        # A legacy organization and a user, as production has them: no
        # id property. The user is a member of it.
        await self.graph.execute(
            'CREATE (o:Organization {{slug: {slug}, name: {slug}}})'
            ' CREATE (u:User {{email: {email}, display_name: "L",'
            ' is_active: true}})'
            ' CREATE (u)-[:MEMBER_OF {{role: "developer"}}]->(o)'
            ' RETURN 1 AS ok',
            {'slug': self.legacy, 'email': self.legacy_user},
            ['ok'],
        )
        self.addAsyncCleanup(self._drop_legacy)

    async def _drop_legacy(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.slug = {slug} OR n.email = {email}'
            ' DETACH DELETE n RETURN 1 AS ok',
            {'slug': self.legacy, 'email': self.legacy_user},
            ['ok'],
        )

    async def id_of(self, label: str, key: str, value: str) -> object:
        records = await self.graph.execute(
            f'MATCH (n:{label} {{{{{key}: {{value}}}}}}) RETURN n.id AS id',
            {'value': value},
            ['id'],
        )
        return records[0]['id'] if records else None

    def auth(self) -> permissions.AuthContext:
        return permissions.AuthContext(
            user=self.user.model_copy(update={'email': self.legacy_user}),
            session_id='s',
            auth_method='jwt',
        )

    async def test_check_member_fails_closed_without_an_id(self) -> None:
        with (
            self.assertRaises(fastapi.HTTPException) as ctx,
            self.assertLogs('imbi.api.auth.organizations', 'ERROR'),
        ):
            await organizations.check_member(
                self.legacy, self.graph, self.auth()
            )
        self.assertEqual(ctx.exception.status_code, 500)

    async def test_backfill_gives_ids_and_keeps_existing_ones(self) -> None:
        kept = await self.id_of('Organization', 'slug', self.org)
        counts = await graph_ids.backfill(self.graph)
        self.assertGreaterEqual(counts['Organization'], 1)
        self.assertGreaterEqual(counts['User'], 1)
        legacy = await self.id_of('Organization', 'slug', self.legacy)
        user = await self.id_of('User', 'email', self.legacy_user)
        self.assertTrue(legacy)
        self.assertTrue(user)
        self.assertEqual(
            await self.id_of('Organization', 'slug', self.org), kept
        )
        # The member check now gives the new id, and a second run
        # changes nothing.
        org_id = await organizations.check_member(
            self.legacy, self.graph, self.auth()
        )
        self.assertNotEqual(org_id, 'None')
        await graph_ids.backfill(self.graph)
        self.assertEqual(
            await self.id_of('Organization', 'slug', self.legacy), legacy
        )
