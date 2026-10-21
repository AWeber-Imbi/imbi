"""Permissions on the routes of one organization (issue #455)."""

import datetime
import unittest
import uuid

from imbi.api.auth import organizations, permissions
from imbi.common import graph, models


class OrgPermissionsTestCase(unittest.IsolatedAsyncioTestCase):
    """A user who can write in org A and only read in org B."""

    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org_a = f'perm-a-{suffix}'
        self.org_b = f'perm-b-{suffix}'
        self.email = f'perm-{suffix}@example.com'
        self.read = f'perm{suffix}:read'
        self.write = f'perm{suffix}:write'
        self.ids = [
            self.org_a,
            self.org_b,
            self.email,
            f'writer-{suffix}',
            f'reader-{suffix}',
            self.read,
            self.write,
        ]
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (a:Organization {{id: {a}, slug: {a}, name: {a}}})
            CREATE (b:Organization {{id: {b}, slug: {b}, name: {b}}})
            CREATE (pr:Permission {{id: {read}, name: {read}}})
            CREATE (pw:Permission {{id: {write}, name: {write}}})
            CREATE (rr:Role {{id: {reader}, slug: {reader}}})
            CREATE (rw:Role {{id: {writer}, slug: {writer}}})
            CREATE (rr)-[:GRANTS]->(pr)
            CREATE (rw)-[:GRANTS]->(pw)
            CREATE (rw)-[:INHERITS_FROM]->(rr)
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'P', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: {writer}}}]->(a)
            CREATE (u)-[:MEMBER_OF {{role: {reader}}}]->(b)
            RETURN 1 AS ok
            """,
            {
                'a': self.org_a,
                'b': self.org_b,
                'read': self.read,
                'write': self.write,
                'reader': f'reader-{suffix}',
                'writer': f'writer-{suffix}',
                'email': self.email,
            },
            ['ok'],
        )

    async def _cleanup(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': self.ids},
            ['ok'],
        )
        await self.graph.close()

    def auth(self, granted: set[str]) -> permissions.AuthContext:
        return permissions.AuthContext(
            user=models.User(
                id=self.email,
                email=self.email,
                display_name='P',
                is_active=True,
                is_admin=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='s',
            auth_method='jwt',
            permissions=granted,
        )

    async def test_check_member_keeps_only_the_role_in_that_org(self) -> None:
        both = {self.read, self.write}
        auth = self.auth(set(both))
        await organizations.check_member(self.org_b, self.graph, auth)
        self.assertEqual(auth.permissions, {self.read})
        auth = self.auth(set(both))
        await organizations.check_member(self.org_a, self.graph, auth)
        self.assertEqual(auth.permissions, both)

    async def test_api_key_scopes_still_limit(self) -> None:
        auth = self.auth({self.read})
        self.assertEqual(
            await organizations.org_permissions(self.graph, auth, self.org_a),
            {self.read},
        )
