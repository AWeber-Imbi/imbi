"""Tests for internal service account seeding."""

import typing
import unittest
from unittest import mock

from imbi.api.auth import internal_services

SCHEDULER = internal_services.INTERNAL_SERVICES[0]
GATEWAY = internal_services.INTERNAL_SERVICES[1]


class FakeGraph:
    """A ``graph.Graph`` stand-in that answers queries by substring.

    The seeding path issues several distinct queries per service, so a
    single ``return_value`` cannot express "the membership edge is
    missing but the role exists". Responses are matched against the
    Cypher text in insertion order, and every query is recorded so a
    test can assert what was *not* issued.
    """

    def __init__(self, responses: dict[str, list[dict[str, object]]]) -> None:
        self._responses = responses
        self.queries: list[str] = []
        self.created: list[object] = []
        self.matched: list[dict[str, typing.Any] | None] = []
        self.match_result: list[object] = []

    async def execute(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append(query)
        for fragment, response in self._responses.items():
            if fragment in query:
                return response
        if 'CREATE (n:' in query:
            # A CREATE against an existing account always returns its
            # row; an empty result there means "account not found",
            # which is a different test's business.
            return [{'n': 'created'}]
        return []

    async def match(
        self,
        node_type: type,
        params: dict[str, typing.Any] | None = None,
        order_by: str | None = None,
    ) -> list[object]:
        self.matched.append(params)
        return self.match_result

    async def create(self, node: object) -> object:
        self.created.append(node)
        return node

    def issued(self, fragment: str) -> list[str]:
        """Return the recorded queries containing *fragment*."""
        return [query for query in self.queries if fragment in query]


class InternalServiceSeedTestCase(unittest.IsolatedAsyncioTestCase):
    """Behavior shared by both internal services."""

    def setUp(self) -> None:
        super().setUp()
        # Argon2 is deliberately slow; the hash's content is irrelevant
        # here, only that it reaches the query.
        self.enterContext(
            mock.patch.object(
                internal_services.password,
                'hash_password',
                side_effect=lambda secret: f'hashed:{secret}',
            )
        )
        self.enterContext(
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda value: value,
            )
        )

    async def test_accounts_and_memberships_created(self) -> None:
        """A fresh install creates both accounts and both memberships."""
        db = FakeGraph({'MERGE (s)-[m:MEMBER_OF]->(o)': [{'m': 'edge'}]})

        results = await internal_services.seed_internal_services(
            db, 'aweber', {}
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [result.service.slug for result in results],
            ['imbi-scheduler', 'imbi-gateway'],
        )
        self.assertTrue(all(result.account_created for result in results))
        self.assertEqual(
            [node.slug for node in db.created],  # pyright: ignore[reportAttributeAccessIssue]
            ['imbi-scheduler', 'imbi-gateway'],
        )
        self.assertEqual(len(db.issued('MERGE (s)-[m:MEMBER_OF]->(o)')), 2)

    async def test_existing_membership_is_left_alone(self) -> None:
        """A role an operator widened is not reset to the seeded one."""
        db = FakeGraph({'RETURN m.role AS role': [{'role': 'admin'}]})

        await internal_services.seed_internal_services(db, 'aweber', {})

        self.assertEqual(db.issued('MERGE (s)-[m:MEMBER_OF]->(o)'), [])

    async def test_missing_role_raises(self) -> None:
        """A role the seed has not created yet fails loudly."""
        db = FakeGraph({})

        with self.assertRaises(internal_services.SeedError) as ctx:
            await internal_services.seed_internal_services(db, 'aweber', {})

        self.assertIn('imbi-scheduler', str(ctx.exception))
        self.assertIn('role or organization not found', str(ctx.exception))

    async def test_existing_account_is_not_recreated(self) -> None:
        """An account already present is not written again."""
        db = FakeGraph({'MERGE (s)-[m:MEMBER_OF]->(o)': [{'m': 'edge'}]})
        db.match_result = [object()]

        results = await internal_services.seed_internal_services(
            db, 'aweber', {}
        )

        self.assertFalse(any(result.account_created for result in results))
        self.assertEqual(db.created, [])


class ClientCredentialTestCase(unittest.IsolatedAsyncioTestCase):
    """Credential handling for imbi-scheduler."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            mock.patch.object(
                internal_services.password,
                'hash_password',
                side_effect=lambda secret: f'hashed:{secret}',
            )
        )
        self.enterContext(
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda value: value,
            )
        )

    async def test_environment_value_is_written(self) -> None:
        """A supplied credential is created with the supplied client id."""
        db = FakeGraph({'MERGE (s)-[m:MEMBER_OF]->(o)': [{'m': 'edge'}]})

        outcome, emit = await internal_services._ensure_client_credential(
            db,
            SCHEDULER,
            {
                'IMBI_SCHEDULER_SA_CLIENT_ID': 'cc_supplied',
                'IMBI_SCHEDULER_SA_CLIENT_SECRET': 'shhh',
            },
        )

        self.assertEqual(outcome, 'supplied')
        self.assertEqual(emit, {})
        self.assertEqual(len(db.issued('CREATE (n:ClientCredential')), 1)

    async def test_environment_value_repoints_existing(self) -> None:
        """A credential the environment names has its hash rewritten."""
        db = FakeGraph({'SET c.client_secret_hash': [{'c': 'credential'}]})

        outcome, _emit = await internal_services._ensure_client_credential(
            db,
            SCHEDULER,
            {
                'IMBI_SCHEDULER_SA_CLIENT_ID': 'cc_supplied',
                'IMBI_SCHEDULER_SA_CLIENT_SECRET': 'shhh',
            },
        )

        self.assertEqual(outcome, 'supplied')
        self.assertEqual(db.issued('CREATE (n:ClientCredential'), [])

    async def test_existing_credential_is_not_rotated(self) -> None:
        """Re-seeding leaves a live credential exactly as it was."""
        db = FakeGraph({'RETURN count(c) AS live': [{'live': 1}]})

        outcome, emit = await internal_services._ensure_client_credential(
            db, SCHEDULER, {}
        )

        self.assertEqual(outcome, 'unchanged')
        self.assertEqual(emit, {})
        self.assertEqual(db.issued('CREATE (n:ClientCredential'), [])
        self.assertEqual(db.issued('SET c.client_secret_hash'), [])

    async def test_revoked_credential_does_not_suppress_seeding(self) -> None:
        """A revoked credential is not a credential."""
        db = FakeGraph({'RETURN count(c) AS live': [{'live': 0}]})

        outcome, _emit = await internal_services._ensure_client_credential(
            db, SCHEDULER, {}
        )

        self.assertEqual(outcome, 'generated')

    async def test_live_check_tolerates_a_missing_revoked_property(
        self,
    ) -> None:
        """The liveness filter coalesces rather than comparing to null.

        ``c.revoked = false`` is null on a node predating the property,
        so a live credential would read as missing and every run would
        mint another one and print another secret.
        """
        db = FakeGraph({'RETURN count(c) AS live': [{'live': 1}]})

        await internal_services._ensure_client_credential(db, SCHEDULER, {})

        self.assertIn(
            'coalesce(c.revoked, false) = false',
            db.issued('RETURN count(c) AS live')[0],
        )

    async def test_generated_credential_is_emitted(self) -> None:
        """Nothing supplied and nothing stored mints a printable pair."""
        db = FakeGraph({})

        outcome, emit = await internal_services._ensure_client_credential(
            db, SCHEDULER, {}
        )

        self.assertEqual(outcome, 'generated')
        self.assertEqual(
            sorted(emit),
            [
                'IMBI_SCHEDULER_SA_CLIENT_ID',
                'IMBI_SCHEDULER_SA_CLIENT_SECRET',
            ],
        )
        self.assertTrue(
            emit['IMBI_SCHEDULER_SA_CLIENT_ID'].startswith('cc_'),
        )
        self.assertEqual(len(db.issued('CREATE (n:ClientCredential')), 1)

    async def test_client_id_without_secret_raises(self) -> None:
        """Half a supplied credential fails loudly, seeding nothing.

        Generating a different pair instead would leave the deployment
        holding a client id whose secret the database has never seen, so
        the service starts and authenticates nobody.
        """
        db = FakeGraph({})

        with self.assertRaises(internal_services.SeedError) as ctx:
            await internal_services._ensure_client_credential(
                db, SCHEDULER, {'IMBI_SCHEDULER_SA_CLIENT_ID': 'cc_supplied'}
            )

        self.assertIn('IMBI_SCHEDULER_SA_CLIENT_SECRET', str(ctx.exception))
        self.assertEqual(db.issued('CREATE (n:ClientCredential'), [])

    async def test_secret_without_client_id_raises(self) -> None:
        """The mirror case: a secret naming nothing to verify it."""
        db = FakeGraph({})

        with self.assertRaises(internal_services.SeedError) as ctx:
            await internal_services._ensure_client_credential(
                db, SCHEDULER, {'IMBI_SCHEDULER_SA_CLIENT_SECRET': 'shhh'}
            )

        self.assertIn('IMBI_SCHEDULER_SA_CLIENT_ID', str(ctx.exception))
        self.assertEqual(db.issued('CREATE (n:ClientCredential'), [])


class ApiKeyTestCase(unittest.IsolatedAsyncioTestCase):
    """Credential handling for imbi-gateway."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            mock.patch.object(
                internal_services.password,
                'hash_password',
                side_effect=lambda secret: f'hashed:{secret}',
            )
        )
        self.enterContext(
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda value: value,
            )
        )

    async def test_supplied_key_is_written(self) -> None:
        """The ik_<id>_<secret> form is split the way auth splits it."""
        db = FakeGraph({})

        outcome, emit = await internal_services._ensure_api_key(
            db, GATEWAY, {'ACTIONS_IMBI_TOKEN': 'ik_abc123_s3cret_value'}
        )

        self.assertEqual(outcome, 'supplied')
        self.assertEqual(emit, {})
        created = db.issued('CREATE (n:APIKey')
        self.assertEqual(len(created), 1)

    async def test_malformed_key_raises(self) -> None:
        """A token no request could authenticate is refused at seed time."""
        db = FakeGraph({})

        with self.assertRaises(internal_services.SeedError) as ctx:
            await internal_services._ensure_api_key(
                db, GATEWAY, {'ACTIONS_IMBI_TOKEN': 'not-an-imbi-key'}
            )

        self.assertIn('ACTIONS_IMBI_TOKEN', str(ctx.exception))

    async def test_generated_key_is_emitted_whole(self) -> None:
        """The emitted value is the full key, not just its secret half."""
        db = FakeGraph({})

        outcome, emit = await internal_services._ensure_api_key(
            db, GATEWAY, {}
        )

        self.assertEqual(outcome, 'generated')
        self.assertTrue(emit['ACTIONS_IMBI_TOKEN'].startswith('ik_'))
        self.assertIsNotNone(
            internal_services._parse_api_key(emit['ACTIONS_IMBI_TOKEN']),
        )

    async def test_supplied_key_repoints_existing(self) -> None:
        """A key the environment names has its hash rewritten."""
        db = FakeGraph({'SET k.key_hash': [{'k': 'key'}]})

        outcome, _emit = await internal_services._ensure_api_key(
            db, GATEWAY, {'ACTIONS_IMBI_TOKEN': 'ik_abc123_s3cret'}
        )

        self.assertEqual(outcome, 'supplied')
        self.assertEqual(db.issued('CREATE (n:APIKey'), [])

    async def test_missing_account_raises(self) -> None:
        """A credential cannot be wired to an account that is not there."""
        db = FakeGraph({'CREATE (n:APIKey': []})

        with self.assertRaises(internal_services.SeedError) as ctx:
            await internal_services._ensure_api_key(
                db, GATEWAY, {'ACTIONS_IMBI_TOKEN': 'ik_abc123_s3cret'}
            )

        self.assertIn('imbi-gateway', str(ctx.exception))

    async def test_existing_key_is_not_rotated(self) -> None:
        """Re-seeding leaves a live API key exactly as it was."""
        db = FakeGraph({'RETURN count(c) AS live': [{'live': 1}]})

        outcome, emit = await internal_services._ensure_api_key(
            db, GATEWAY, {}
        )

        self.assertEqual(outcome, 'unchanged')
        self.assertEqual(emit, {})
        self.assertEqual(db.issued('CREATE (n:APIKey'), [])


class ParseApiKeyTestCase(unittest.TestCase):
    """``_parse_api_key`` accepts exactly what authentication accepts."""

    def test_valid_key(self) -> None:
        self.assertEqual(
            internal_services._parse_api_key('ik_abcd_secret_with_underscore'),
            ('ik_abcd', 'secret_with_underscore'),
        )

    def test_rejected_forms(self) -> None:
        for value in ('', 'ik', 'ik_abcd', 'xx_abcd_secret', 'ik__secret'):
            with self.subTest(value=value):
                self.assertIsNone(internal_services._parse_api_key(value))


class InternalServiceTableTestCase(unittest.TestCase):
    """Invariants of the :data:`INTERNAL_SERVICES` table."""

    def test_client_id_var_present_for_client_credentials(self) -> None:
        """Only API keys may omit ``client_id_var``.

        ``_ensure_client_credential`` reads it unconditionally, so a
        client-credential entry without one would fail at seed time.
        """
        for service in internal_services.INTERNAL_SERVICES:
            with self.subTest(service=service.slug):
                if service.credential == 'client_credential':
                    self.assertIsNotNone(service.client_id_var)
                else:
                    self.assertIsNone(service.client_id_var)

    def test_roles_are_seeded(self) -> None:
        """Every role named here is one ``seed_default_roles`` creates."""
        from imbi.api.auth import seed

        seeded = {role[0] for role in seed.DEFAULT_ROLES}
        for service in internal_services.INTERNAL_SERVICES:
            with self.subTest(service=service.slug):
                self.assertIn(service.role_slug, seeded)
