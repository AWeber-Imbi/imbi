"""Tests for the AI model resolver, against the test graph."""

import typing
import unittest
import uuid

import dotenv

from imbi.common import graph
from imbi.common.llm import resolve

dotenv.load_dotenv()


class ResolveModelTestCase(unittest.IsolatedAsyncioTestCase):
    """Two organizations with one team each. The member is in team A.

    Models of organization A: ``chat`` (everyone), ``locked`` (team A
    only), and ``off`` (disabled). Of organization B: ``q`` (its provider
    is disabled).
    """

    async def asyncSetUp(self) -> None:
        self.graph = graph.Graph()
        await self.graph.open()
        sfx = uuid.uuid4().hex[:10]
        self.sfx = sfx
        self.ids = {
            name: f'{name}-{sfx}'
            for name in (
                'org-a',
                'org-b',
                'team-a',
                'team-b',
                'p',
                'q-p',
                'chat',
                'locked',
                'off',
                'q',
            )
        }
        self.member = f'member-{sfx}@example.com'
        self.other = f'other-{sfx}@example.com'
        await self.graph.execute(
            """
            CREATE (a:Organization {{id: {org_a}, slug: {org_a}, name: 'A'}})
            CREATE (b:Organization {{id: {org_b}, slug: {org_b}, name: 'B'}})
            CREATE (ta:Team {{id: {team_a}, slug: {team_a}, name: 'TA'}})
            CREATE (tb:Team {{id: {team_b}, slug: {team_b}, name: 'TB'}})
            CREATE (ta)-[:BELONGS_TO]->(a)
            CREATE (tb)-[:BELONGS_TO]->(b)
            CREATE (u:User {{email: {member}, display_name: 'M'}})
            CREATE (u)-[:MEMBER_OF]->(ta)
            CREATE (o:User {{email: {other}, display_name: 'O'}})
            CREATE (o)-[:MEMBER_OF]->(tb)
            CREATE (p:AIProvider {{id: {p}, slug: {p}, name: 'P',
                                   driver: 'anthropic', enabled: true}})
            CREATE (qp:AIProvider {{id: {q_p}, slug: {q_p}, name: 'Q',
                                    driver: 'anthropic', enabled: false}})
            CREATE (chat:AIModel {{id: {chat}, slug: {chat}, name: 'C',
                                   model_id: 'claude-chat', enabled: true,
                                   access_scope: 'organization'}})
            CREATE (locked:AIModel {{id: {locked}, slug: {locked},
                                     name: 'L', model_id: 'claude-locked',
                                     enabled: true,
                                     access_scope: 'restricted'}})
            CREATE (off:AIModel {{id: {off}, slug: {off}, name: 'O',
                                  model_id: 'claude-off', enabled: false}})
            CREATE (q:AIModel {{id: {q}, slug: {q}, name: 'Q',
                                model_id: 'claude-q', enabled: true}})
            CREATE (chat)-[:SERVED_BY]->(p)
            CREATE (locked)-[:SERVED_BY]->(p)
            CREATE (off)-[:SERVED_BY]->(p)
            CREATE (q)-[:SERVED_BY]->(qp)
            CREATE (locked)-[:ALLOWED_FOR]->(ta)
            CREATE (p)-[:BELONGS_TO]->(a)
            CREATE (chat)-[:BELONGS_TO]->(a)
            CREATE (locked)-[:BELONGS_TO]->(a)
            CREATE (off)-[:BELONGS_TO]->(a)
            CREATE (qp)-[:BELONGS_TO]->(b)
            CREATE (q)-[:BELONGS_TO]->(b)
            RETURN a.id AS id
            """,
            {
                **{k.replace('-', '_'): v for k, v in self.ids.items()},
                'member': self.member,
                'other': self.other,
            },
            ['id'],
        )

    async def asyncTearDown(self) -> None:
        await self.graph.execute(
            """
            MATCH (n)
            WHERE n.id IN {ids} OR n.email IN {emails}
            DETACH DELETE n
            """,
            {
                'ids': list(self.ids.values()),
                'emails': [self.member, self.other],
            },
        )
        await self.graph.close()

    async def set_default(self, label: str, source: str, model: str) -> None:
        query: typing.LiteralString = (
            """
            MATCH (s:Organization {{id: {source}}})
            MATCH (m:AIModel {{id: {model}}})
            CREATE (s)-[:USES_DEFAULT_MODEL]->(m)
            """
            if label == 'Organization'
            else """
            MATCH (s:Team {{id: {source}}})
            MATCH (m:AIModel {{id: {model}}})
            CREATE (s)-[:USES_DEFAULT_MODEL]->(m)
            """
        )
        await self.graph.execute(
            query, {'source': self.ids[source], 'model': self.ids[model]}
        )

    async def resolve(self, **kwargs: typing.Any) -> resolve.ResolvedModel:
        org = kwargs.pop('org', 'org-a')
        for key in ('model', 'team_id'):
            if key in kwargs:
                kwargs[key] = self.ids[kwargs[key]]
        org_ids = [
            self.ids[o] for o in (org if isinstance(org, list) else [org])
        ]
        return await resolve.resolve_model(self.graph, org_ids, **kwargs)

    async def assert_unusable(self, reason: str, **kwargs: typing.Any) -> None:
        with self.assertRaises(resolve.ModelUnusable) as raised:
            await self.resolve(**kwargs)
        self.assertEqual(raised.exception.reason, reason)

    async def test_explicit_by_slug_or_id(self) -> None:
        found = await self.resolve(model='chat')
        self.assertEqual(found.source, 'explicit')
        assert found.model is not None
        self.assertEqual(found.model.model_id, 'claude-chat')
        self.assertEqual(found.model.provider.driver, 'anthropic')
        # A consumer with no organization reads each organization of
        # the user.
        found = await self.resolve(org=['org-b', 'org-a'], model='chat')
        self.assertEqual(found.source, 'explicit')
        # A model of another organization is not found.
        await self.assert_unusable('not_found', org='org-b', model='chat')

    async def test_explicit_by_vendor_model_id(self) -> None:
        found = await resolve.resolve_model(
            self.graph, [self.ids['org-a']], model_id='claude-chat'
        )
        self.assertEqual(found.source, 'explicit')
        assert found.model is not None
        self.assertEqual(found.model.slug, self.ids['chat'])
        for org, model_id, reason in (
            ('org-a', 'claude-nope', 'not_found'),
            # The id of a model of another organization is not found.
            ('org-b', 'claude-chat', 'not_found'),
            ('org-a', 'claude-off', 'disabled'),
        ):
            with (
                self.subTest(model_id=model_id),
                self.assertRaises(resolve.ModelUnusable) as raised,
            ):
                await resolve.resolve_model(
                    self.graph, [self.ids[org]], model_id=model_id
                )
            self.assertEqual(raised.exception.reason, reason)

    async def test_explicit_errors(self) -> None:
        with self.assertRaises(resolve.ModelUnusable) as raised:
            await resolve.resolve_model(self.graph, [], model='no-such')
        self.assertEqual(raised.exception.reason, 'not_found')
        await self.assert_unusable('disabled', model='off')
        await self.assert_unusable('provider_disabled', org='org-b', model='q')

    async def test_drivers(self) -> None:
        found = await self.resolve(model='chat', drivers=('anthropic',))
        self.assertEqual(found.source, 'explicit')
        await self.assert_unusable(
            'unsupported_driver', model='chat', drivers=('typesafe',)
        )

    async def test_restricted_access(self) -> None:
        ok: list[dict[str, typing.Any]] = [
            {'email': self.member},
            {'team_id': 'team-a'},
            {'admin': True},
        ]
        for kwargs in ok:
            with self.subTest(**kwargs):
                found = await self.resolve(model='locked', **kwargs)
                self.assertEqual(found.source, 'explicit')
        refused: list[dict[str, typing.Any]] = [
            {},
            {'email': self.other},
            {'team_id': 'team-b'},
            {'email': self.member, 'team_id': 'team-b'},
        ]
        for kwargs in refused:
            with self.subTest(**kwargs):
                await self.assert_unusable(
                    'not_allowed', model='locked', **kwargs
                )

    async def test_order(self) -> None:
        self.assertEqual((await self.resolve()).source, 'env')
        self.assertIsNone((await self.resolve()).model)
        await self.set_default('Organization', 'org-a', 'chat')
        found = await self.resolve(team_id='team-a')
        self.assertEqual(found.source, 'org')
        await self.set_default('Team', 'team-a', 'locked')
        found = await self.resolve(team_id='team-a')
        self.assertEqual(found.source, 'team')
        assert found.model is not None
        self.assertEqual(found.model.model_id, 'claude-locked')
        # The explicit model wins over both defaults.
        found = await self.resolve(model='chat', team_id='team-a')
        self.assertEqual(found.source, 'explicit')

    async def test_unusable_default_does_not_fall_through(self) -> None:
        await self.set_default('Organization', 'org-a', 'chat')
        await self.set_default('Team', 'team-a', 'off')
        await self.assert_unusable('disabled', team_id='team-a')
        await self.set_default('Organization', 'org-b', 'q')
        await self.assert_unusable('provider_disabled', org='org-b')

    async def test_restricted_default_needs_an_allowed_user(self) -> None:
        await self.set_default('Organization', 'org-a', 'locked')
        await self.assert_unusable('not_allowed', email=self.other)
        found = await self.resolve(email=self.member)
        self.assertEqual(found.source, 'org')

    async def test_defaults_are_scoped_to_the_organization(self) -> None:
        await self.set_default('Organization', 'org-a', 'chat')
        await self.set_default('Team', 'team-b', 'off')
        # Organization B has no default of its own.
        self.assertEqual((await self.resolve(org='org-b')).source, 'env')
        # Team B is not in organization A, so its default is not read.
        found = await self.resolve(org='org-a', team_id='team-b')
        self.assertEqual(found.source, 'org')
