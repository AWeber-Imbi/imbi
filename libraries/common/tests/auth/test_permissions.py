"""Tests for permission resolution and the auth context.

These cover :mod:`imbi.common.auth.permissions`. The resource-level
``CAN_ACCESS`` case stays in ``apps/api/tests/auth/test_permissions.py``
with the imbi-api helpers it exercises.
"""

import datetime
import unittest
from unittest import mock

import fastapi

from imbi.common import models
from imbi.common.auth import permissions


class OrgMembershipPermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading via org membership model."""

    async def test_load_permissions_from_org_membership(self) -> None:
        """Test loading permissions from org membership role."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',
                ]
            }
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'User', 'email', 'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_with_role_inheritance(self) -> None:
        """Test loading permissions with role inheritance."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',  # From parent role
                ]
            }
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'User', 'email', 'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_multiple_org_memberships(
        self,
    ) -> None:
        """Test permissions from multiple org memberships are merged."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'role:read',
                    'user:read',
                ]
            }
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'User', 'email', 'testuser@example.com'
            )

        self.assertIn('blueprint:read', perms)
        self.assertIn('role:read', perms)
        self.assertIn('user:read', perms)

    async def test_load_permissions_no_memberships(self) -> None:
        """Test empty permissions for user with no org memberships."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        perms = await permissions.load_principal_permissions(
            mock_db, 'User', 'email', 'nobody@example.com'
        )

        self.assertEqual(perms, set())

    async def test_query_does_not_use_zero_hop_variable_length(
        self,
    ) -> None:
        """Guard against regressing to ``*0..``.

        Apache AGE does not honor the zero-hop case in variable-length
        paths, so the assigned role's own GRANTS would be silently
        excluded. The query must collect ancestors with ``*1..`` and
        union the start role back in.
        """
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        await permissions.load_principal_permissions(
            mock_db, 'User', 'email', 'someone@example.com'
        )

        query = mock_db.execute.call_args.args[0]
        self.assertNotIn('*0..', query)
        self.assertIn('*1..', query)
        self.assertIn('ancestors + [r]', query)


class PermissionDeduplicationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test duplicate permissions from multiple sources are deduped."""

    async def test_deduplicate_permissions(self) -> None:
        """Test that duplicate permissions are deduplicated."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:read',  # Duplicate
                    'blueprint:write',
                    'project:read',
                    'project:read',  # Duplicate
                ]
            }
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'User', 'email', 'testuser@example.com'
            )

        # Should be deduplicated to a set
        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )
        self.assertEqual(len(perms), 3)  # No duplicates


class AuthContextTestCase(unittest.TestCase):
    """Test AuthContext properties for users and service accounts."""

    def test_auth_context_principal_name_user(self) -> None:
        """User principal returns email."""
        user = models.User(
            email='user@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            user=user,
            session_id='sess-1',
            auth_method='jwt',
            permissions={'project:read'},
        )
        self.assertEqual(ctx.principal_name, 'user@example.com')

    def test_auth_context_principal_name_service_account(
        self,
    ) -> None:
        """Service account principal returns slug."""
        sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            service_account=sa,
            session_id='sess-2',
            auth_method='client_credentials',
            permissions={'project:read'},
        )
        self.assertEqual(ctx.principal_name, 'deploy-bot')

    def test_auth_context_is_admin_user(self) -> None:
        """Admin user returns True for is_admin."""
        user = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            user=user,
            session_id='sess-3',
            auth_method='jwt',
        )
        self.assertTrue(ctx.is_admin)

    def test_auth_context_is_admin_service_account(self) -> None:
        """Service account always returns False for is_admin."""
        sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            service_account=sa,
            session_id='sess-4',
            auth_method='client_credentials',
        )
        self.assertFalse(ctx.is_admin)


class ServiceAccountPermissionTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test service account permission loading."""

    async def test_load_service_account_permissions(self) -> None:
        """Test loading permissions for a SA via graph."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'project:read',
                    'project:write',
                    'blueprint:read',
                ]
            }
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'ServiceAccount', 'slug', 'deploy-bot'
            )

        self.assertEqual(
            perms,
            {'project:read', 'project:write', 'blueprint:read'},
        )

    async def test_authenticate_jwt_client_credentials(
        self,
    ) -> None:
        """JWT with auth_method=client_credentials loads SA."""
        # `imbi.common`, not `imbi.api`: this suite must not require imbi-api
        # to be installed, and reaching into the API's settings singleton
        # inverts the dependency direction the extraction was for. Matches
        # what the sibling `test_authorization.py` does.
        from imbi.common import settings
        from imbi.common.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
        )

        # Create a token with client_credentials auth_method
        token = core.create_access_token(
            'deploy-bot',
            extra_claims={'auth_method': 'client_credentials'},
            auth_settings=auth_settings,
        )

        test_sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            if 'MEMBER_OF' in query:
                # Permissions query (contains both ServiceAccount
                # and MEMBER_OF)
                return [{'permissions': ['project:read']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for SA lookup
        mock_db.match.return_value = [test_sa]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            ctx = await permissions.authenticate_jwt(
                mock_db, token, auth_settings
            )

        self.assertIsNotNone(ctx.service_account)
        self.assertIsNone(ctx.user)
        self.assertEqual(ctx.service_account.slug, 'deploy-bot')
        self.assertEqual(ctx.auth_method, 'client_credentials')
        self.assertIn('project:read', ctx.permissions)

    async def test_authenticate_jwt_client_credentials_scope(
        self,
    ) -> None:
        """#484: the scope claim limits a client-credentials token."""
        from imbi.common import settings
        from imbi.common.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long'
        )
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [
            models.ServiceAccount(
                slug='deploy-bot',
                display_name='Deploy Bot',
                is_active=True,
                created_at=datetime.datetime.now(datetime.UTC),
            )
        ]

        def execute_side_effect(query, params=None, columns=None):
            if 'MEMBER_OF' in query:
                return [{'permissions': ['project:read', 'project:write']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        for claims, expected in (
            ({}, {'project:read', 'project:write'}),
            ({'scope': 'project:read blueprint:read'}, {'project:read'}),
        ):
            token = core.create_access_token(
                'deploy-bot',
                extra_claims={'auth_method': 'client_credentials', **claims},
                auth_settings=auth_settings,
            )
            with mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ):
                ctx = await permissions.authenticate_jwt(
                    mock_db, token, auth_settings
                )
            self.assertEqual(expected, ctx.permissions, claims)

    async def test_authenticate_jwt_channel_claim(self) -> None:
        """A user JWT's ``channel`` claim sets the context channel."""
        from imbi.common import settings
        from imbi.common.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
        )
        user = models.User(
            email='ada@example.com',
            display_name='Ada',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        mock_db = mock.AsyncMock()
        mock_db.execute = mock.AsyncMock(return_value=[])
        mock_db.match.return_value = [user]
        cases: list[tuple[dict[str, str] | None, str | None]] = [
            ({'channel': 'slack'}, 'slack'),
            ({'channel': 'web'}, None),
            (None, None),
        ]
        for claims, expected in cases:
            with self.subTest(claims=claims):
                token = core.create_access_token(
                    user.email,
                    extra_claims=claims,
                    auth_settings=auth_settings,
                )
                ctx = await permissions.authenticate_jwt(
                    mock_db, token, auth_settings
                )
                self.assertEqual(ctx.auth_method, 'jwt')
                self.assertEqual(ctx.channel, expected)


class ApiKeyAccessLogPrincipalTestCase(unittest.IsolatedAsyncioTestCase):
    """`_authenticate_token` registers the API-key owner for the log."""

    def _ctx(self) -> permissions.AuthContext:
        return permissions.AuthContext(
            user=models.User(
                email='dev@example.com',
                display_name='Dev',
                is_active=True,
                is_admin=False,
                password_hash='x',
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='ik_abc123',
            auth_method='api_key',
        )

    async def test_api_key_registers_owner(self) -> None:
        ctx = self._ctx()
        with (
            mock.patch.object(
                permissions,
                'authenticate_api_key',
                mock.AsyncMock(return_value=ctx),
            ),
            mock.patch.object(
                permissions.access_log, 'remember_api_key_principal'
            ) as remember,
        ):
            result = await permissions._authenticate_token(
                mock.AsyncMock(), 'ik_abc123_secret', mock.Mock()
            )
        self.assertIs(result, ctx)
        remember.assert_called_once_with('ik_abc123', 'dev@example.com')

    async def test_jwt_does_not_register(self) -> None:
        with (
            mock.patch.object(
                permissions,
                'authenticate_jwt',
                mock.AsyncMock(return_value=self._ctx()),
            ),
            mock.patch.object(
                permissions.access_log, 'remember_api_key_principal'
            ) as remember,
        ):
            await permissions._authenticate_token(
                mock.AsyncMock(), 'jwt.token.here', mock.Mock()
            )
        remember.assert_not_called()


class NarrowToAccountableTestCase(unittest.IsolatedAsyncioTestCase):
    """A scheduler request gets only what its accountable principal has."""

    def _scheduler(self) -> permissions.AuthContext:
        return permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-scheduler', display_name='Scheduler'
            ),
            auth_method='client_credentials',
            permissions={'project:read', 'workflow:run'},
        )

    def _user(self, **fields: object) -> models.User:
        values: dict[str, object] = {
            'email': 'dev@example.com',
            'display_name': 'Dev',
            'is_active': True,
            'is_admin': False,
            'created_at': datetime.datetime.now(datetime.UTC),
        }
        values.update(fields)
        return models.User.model_validate(values)

    async def _narrow(
        self,
        ctx: permissions.AuthContext,
        accountable: str | None,
        *,
        principals: list[object] | None = None,
        granted: set[str] | None = None,
    ) -> permissions.AuthContext:
        db = mock.AsyncMock()
        db.match.return_value = principals or []
        with mock.patch.object(
            permissions,
            'load_principal_permissions',
            mock.AsyncMock(return_value=granted or set()),
        ):
            return await permissions.narrow_to_accountable(
                db, ctx, accountable
            )

    async def test_limits_to_the_accountable_user(self) -> None:
        ctx = self._scheduler()
        narrowed = await self._narrow(
            ctx,
            'dev@example.com',
            principals=[self._user()],
            granted={'project:read'},
        )
        self.assertEqual({'project:read'}, narrowed.permissions)
        self.assertEqual(
            ('User', 'email', 'dev@example.com'), narrowed.on_behalf_of
        )
        # A copy: a cached context must not change.
        self.assertEqual({'project:read', 'workflow:run'}, ctx.permissions)

    async def test_refuses_an_inactive_accountable_user(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as raised:
            await self._narrow(
                self._scheduler(),
                'dev@example.com',
                principals=[self._user(is_active=False)],
            )
        self.assertEqual(403, raised.exception.status_code)

    async def test_refuses_an_unknown_accountable_principal(self) -> None:
        with self.assertRaises(fastapi.HTTPException):
            await self._narrow(self._scheduler(), 'gone@example.com')

    async def test_leaves_internal_and_admin_principals_alone(self) -> None:
        ctx = self._scheduler()
        for accountable in permissions.INTERNAL_ACCOUNTABLE:
            self.assertIs(ctx, await self._narrow(ctx, accountable))
        admin = self._user(is_admin=True)
        self.assertIs(
            ctx,
            await self._narrow(ctx, 'dev@example.com', principals=[admin]),
        )

    async def test_ignores_the_header_from_any_other_caller(self) -> None:
        ctx = permissions.AuthContext(
            user=self._user(),
            auth_method='jwt',
            permissions={'project:read'},
        )
        self.assertIs(ctx, await self._narrow(ctx, 'other@example.com'))
