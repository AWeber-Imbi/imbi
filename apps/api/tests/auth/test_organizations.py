"""Permissions on the routes of one organization (issue #455)."""

import datetime
import unittest
import uuid
from unittest import mock

import fastapi
import httpx

from apps.api.tests import support
from imbi.api import scoring
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


class ProjectDeliveryRoutesTestCase(unittest.IsolatedAsyncioTestCase):
    """Deploy and sync routes use the role in the path organization only.

    The user is a developer in org A and read-only in org B, so the
    union of their roles has every write permission these routes need.
    """

    write = (
        'project:deployment:write',
        'project:commits:write',
        'project:pull-requests:write',
    )

    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org_a = f'dlv-a-{suffix}'
        self.org_b = f'dlv-b-{suffix}'
        self.project_a = f'dlv-pa-{suffix}'
        self.project_b = f'dlv-pb-{suffix}'
        self.email = f'dlv-{suffix}@example.com'
        writer, reader = f'dlv-dev-{suffix}', f'dlv-ro-{suffix}'
        self.ids = [
            self.org_a,
            self.org_b,
            self.project_a,
            self.project_b,
            f'dlv-ta-{suffix}',
            f'dlv-tb-{suffix}',
            self.email,
            writer,
            reader,
        ]
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (a:Organization {{id: {a}, slug: {a}, name: {a}}})
            CREATE (b:Organization {{id: {b}, slug: {b}, name: {b}}})
            CREATE (ta:Team {{id: {ta}, slug: {ta}, name: {ta}}})
            CREATE (tb:Team {{id: {tb}, slug: {tb}, name: {tb}}})
            CREATE (ta)-[:BELONGS_TO]->(a)
            CREATE (tb)-[:BELONGS_TO]->(b)
            CREATE (pa:Project {{id: {pa}, slug: {pa}, name: {pa}}})
            CREATE (pb:Project {{id: {pb}, slug: {pb}, name: {pb}}})
            CREATE (pa)-[:OWNED_BY]->(ta)
            CREATE (pb)-[:OWNED_BY]->(tb)
            CREATE (rw:Role {{id: {writer}, slug: {writer}}})
            CREATE (rr:Role {{id: {reader}, slug: {reader}}})
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'D', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: {writer}}}]->(a)
            CREATE (u)-[:MEMBER_OF {{role: {reader}}}]->(b)
            RETURN 1 AS ok
            """,
            {
                'a': self.org_a,
                'b': self.org_b,
                'ta': f'dlv-ta-{suffix}',
                'tb': f'dlv-tb-{suffix}',
                'pa': self.project_a,
                'pb': self.project_b,
                'writer': writer,
                'reader': reader,
                'email': self.email,
            },
            ['ok'],
        )
        # Permission nodes are shared with the seeded roles: merge them
        # and never delete them.
        for name in (*self.write, 'project:deployment:read'):
            await self.graph.execute(
                """
                MERGE (p:Permission {{name: {name}}})
                WITH p
                MATCH (r:Role) WHERE r.slug IN {roles}
                  AND (r.slug = {writer} OR {name} ENDS WITH ':read')
                MERGE (r)-[:GRANTS]->(p)
                RETURN 1 AS ok
                """,
                {
                    'name': name,
                    'roles': [writer, reader],
                    'writer': writer,
                },
                ['ok'],
            )

        user = models.User(
            id=self.email,
            email=self.email,
            display_name='D',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=user,
                session_id='s',
                auth_method='jwt',
                permissions={*self.write, 'project:deployment:read'},
            )

        self.test_app = support.shared_app()
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[scoring._inject_optional_client] = lambda: None
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )
        # Past the authorization dependencies, every route stops here.
        reached = fastapi.HTTPException(status_code=418)
        for target in (
            'imbi.api.endpoints.project_deployments._trigger_deployment',
            'imbi.api.endpoints.project_commit_sync.resolve_capability',
            'imbi.api.endpoints.project_pr_sync.resolve_capability',
        ):
            patcher = mock.patch(target, side_effect=reached)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _cleanup(self) -> None:
        await self.client.aclose()
        self.test_app.dependency_overrides.clear()
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': self.ids},
            ['ok'],
        )
        await self.graph.close()

    async def post_all(self, org: str, project: str) -> list[int]:
        base = f'/organizations/{org}/projects/{project}'
        deploy = {
            'action': 'deploy',
            'environment': 'staging',
            'committish': 'abc1234',
        }
        return [
            (
                await self.client.post(f'{base}/deployments', json=deploy)
            ).status_code,
            (await self.client.post(f'{base}/commits/sync')).status_code,
            (await self.client.post(f'{base}/pull-requests/sync')).status_code,
        ]

    async def test_write_in_the_developer_org(self) -> None:
        self.assertEqual(
            await self.post_all(self.org_a, self.project_a), [418] * 3
        )

    async def test_no_write_in_the_read_only_org(self) -> None:
        self.assertEqual(
            await self.post_all(self.org_b, self.project_b), [403] * 3
        )

    async def test_project_of_another_org_is_not_found(self) -> None:
        self.assertEqual(
            await self.post_all(self.org_b, self.project_a), [404] * 3
        )
