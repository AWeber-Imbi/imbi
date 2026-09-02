"""Deployment endpoints reached by a principal with no acting user.

A service account presenting a client-credentials or API-key token has
no ``IdentityConnection`` and no route to acquire one, so it acts with
the Integration's own credential.  These tests pin the envelope that
fallback is bounded by: the additive ``integration:act-as-service``
grant, organization membership, the environment opt-in, and the refusal
to let a machine acknowledge a CI failure on a human's behalf.

The human paths are covered in ``test_project_deployments.py``; what is
asserted here is that they are *unchanged* by any of it.
"""

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from apps.api.tests.endpoints.test_project_deployments import (
    _FakeDeploymentPlugin,
    _make_resolved,
)
from imbi.api import models
from imbi.api.auth import autonomous, password, permissions, principals
from imbi.api.endpoints.project_deployments import _EnvFlags
from imbi.common import graph

_MODULE = 'imbi.api.endpoints.project_deployments'

_DEPLOY_BODY: dict[str, typing.Any] = {
    'action': 'deploy',
    'environment': 'staging',
    'committish': 'abc1234',
    'ref_label': 'v1.0.0',
}


class _AutonomousBase(support.SharedAppTestCase):
    """Harness whose principal is a service account, not a user."""

    #: Overridden per-case to vary the grant under test.
    granted: typing.ClassVar[set[str]] = {
        'project:deployment:read',
        'project:deployment:write',
        autonomous.ACT_AS_SERVICE_PERMISSION,
    }
    #: Whether the graph answers the organization-membership probe.
    member: typing.ClassVar[bool] = True
    #: The target environment's opt-in flag.
    allow_autonomous: typing.ClassVar[bool] = True

    def setUp(self) -> None:
        self.auth_context = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='rollback-daemon', display_name='Rollback Daemon'
            ),
            auth_method='client_credentials',
            permissions=set(self.granted),
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute = mock.AsyncMock(side_effect=self._execute)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.mocks = {
            'resolve_capability': self._start(
                mock.patch(
                    f'{_MODULE}.resolve_capability',
                    return_value=_make_resolved(
                        _FakeDeploymentPlugin,
                        options={'owner': 'octo', 'repo': 'demo'},
                    ),
                )
            ),
            'lookup_project_slugs': self._start(
                mock.patch(
                    f'{_MODULE}.lookup_project_slugs',
                    return_value=('proj', 'team'),
                )
            ),
            'decrypt_integration_credentials': self._start(
                mock.patch(
                    f'{_MODULE}.decrypt_integration_credentials',
                    return_value={
                        'app_id': '1',
                        'private_key': '-----BEGIN----',
                    },
                )
            ),
            'append_deployment_event': self._start(
                mock.patch(
                    f'{_MODULE}.append_deployment_event', return_value=None
                )
            ),
            '_load_env_flags': self._start(
                mock.patch(
                    f'{_MODULE}._load_env_flags',
                    return_value=_EnvFlags(
                        found=True,
                        can_deploy=True,
                        can_promote=True,
                        allow_autonomous=self.allow_autonomous,
                    ),
                )
            ),
            '_resolve_tag_formats': self._start(
                mock.patch(f'{_MODULE}._resolve_tag_formats', return_value=[])
            ),
            'clickhouse': self._start(
                mock.patch(
                    f'{_MODULE}.clickhouse.client.Clickhouse.get_instance',
                    return_value=mock.MagicMock(
                        insert=mock.AsyncMock(return_value=None),
                        initialize=mock.AsyncMock(return_value=True),
                        setup_schema=mock.AsyncMock(return_value=None),
                        aclose=mock.AsyncMock(return_value=None),
                        close=mock.AsyncMock(return_value=None),
                    ),
                )
            ),
        }

    async def _execute(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        """Answer only the two membership/ownership probes.

        Everything else reads as "no rows" -- the release-block and
        in-flight gates treat any row as a hit, so a blanket truthy
        answer would fail these tests for the wrong reason.
        """
        if 'MEMBER_OF' in query:
            return [{'slug': 'rollback-daemon'}] if self.member else []
        if ':OWNED_BY' in query and 'RETURN p.id AS id' in query:
            return [{'id': 'proj1'}]
        return []

    def _start(self, patcher: typing.Any) -> mock.MagicMock:
        m = patcher.start()
        self.addCleanup(patcher.stop)
        return m

    def _deploy(self, **overrides: typing.Any) -> typing.Any:
        body = dict(_DEPLOY_BODY) | overrides
        with testclient.TestClient(self.test_app) as client:
            return client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json=body,
            )


class AutonomousDeployTestCase(_AutonomousBase):
    def test_deploy_succeeds_with_full_envelope(self) -> None:
        """Both grants, a member org, and an opted-in env: it goes."""
        response = self._deploy()
        self.assertEqual(response.status_code, 202, response.text)

    def test_app_credentials_accepted_without_identity(self) -> None:
        """No 401 identity_required: there is no browser to redirect."""
        response = self._deploy()
        self.assertNotEqual(response.status_code, 401)


class MissingActAsServiceTestCase(_AutonomousBase):
    granted: typing.ClassVar[set[str]] = {
        'project:deployment:read',
        'project:deployment:write',
    }

    def test_capability_permission_alone_is_not_enough(self) -> None:
        response = self._deploy()
        self.assertEqual(response.status_code, 403)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'service_credential_forbidden')
        self.assertEqual(detail['integration_id'], 'p-1')


class NonMemberTestCase(_AutonomousBase):
    member: typing.ClassVar[bool] = False

    def test_org_membership_is_required(self) -> None:
        response = self._deploy()
        self.assertEqual(response.status_code, 403)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'organization_forbidden')
        self.assertEqual(detail['org_slug'], 'myorg')


class EnvironmentNotAutonomousTestCase(_AutonomousBase):
    allow_autonomous: typing.ClassVar[bool] = False

    def test_environment_must_opt_in(self) -> None:
        response = self._deploy()
        self.assertEqual(response.status_code, 403)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'environment_not_autonomous')
        self.assertEqual(detail['environment'], 'staging')


class CiOverrideTestCase(_AutonomousBase):
    def test_acknowledgement_is_refused_on_a_green_commit(self) -> None:
        """Refused on the claim, not on the CI colour.

        ``_FakeDeploymentPlugin`` reports no failing checks, so this
        deploy would otherwise sail through -- which is the point: the
        assertion "an operator reviewed the failure" is false whatever
        CI says.
        """
        response = self._deploy(acknowledge_ci_failure=True)
        self.assertEqual(response.status_code, 403)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'ci_override_forbidden')
        self.assertEqual(detail['committish'], 'abc1234')

    def test_not_acknowledging_is_unaffected(self) -> None:
        response = self._deploy(acknowledge_ci_failure=False)
        self.assertEqual(response.status_code, 202, response.text)


class NoServiceCredentialTestCase(_AutonomousBase):
    def test_missing_credential_stays_a_503(self) -> None:
        """The one row of the contract a retry might fix."""
        self.mocks['decrypt_integration_credentials'].return_value = {}
        response = self._deploy()
        self.assertEqual(response.status_code, 503)
        detail = response.json()['detail']
        self.assertEqual(detail['error'], 'no_service_credential')
        self.assertEqual(detail['integration_id'], 'p-1')


class HumanCallerUnaffectedTestCase(_AutonomousBase):
    """A user keeps the old path even holding none of the new grants."""

    granted: typing.ClassVar[set[str]] = {
        'project:deployment:read',
        'project:deployment:write',
    }
    member: typing.ClassVar[bool] = False
    allow_autonomous: typing.ClassVar[bool] = False

    def setUp(self) -> None:
        super().setUp()
        self.auth_context = permissions.AuthContext(
            user=models.User(
                email='dev@example.com',
                display_name='Dev',
                is_active=True,
                is_admin=False,
                password_hash=password.hash_password('testpassword123'),
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='s',
            auth_method='jwt',
            permissions=set(self.granted),
        )
        self.mocks['attach_identity'] = self._start(
            mock.patch(
                f'{_MODULE}.attach_identity',
                side_effect=lambda db, ctx, resolved, auth: ctx,
            )
        )
        self.mocks['decrypt_integration_credentials'].return_value = {
            'access_token': 'gho_test'
        }

    def test_user_needs_neither_grant_nor_membership_nor_opt_in(self) -> None:
        response = self._deploy()
        self.assertEqual(response.status_code, 202, response.text)

    def test_user_may_still_acknowledge_a_ci_failure(self) -> None:
        response = self._deploy(acknowledge_ci_failure=True)
        self.assertEqual(response.status_code, 202, response.text)


class InternalPrincipalTestCase(unittest.TestCase):
    """Imbi's own workers are userless but not autonomous."""

    def test_system_auth_is_marked_internal(self) -> None:
        auth = principals.system_auth('deployment-sync', 'Deployment Sync')
        self.assertTrue(auth.internal)
        self.assertTrue(autonomous.is_userless(auth))
        self.assertFalse(autonomous.is_autonomous(auth))

    def test_an_authenticated_service_account_is_autonomous(self) -> None:
        auth = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='daemon', display_name='Daemon'
            ),
            auth_method='client_credentials',
        )
        self.assertFalse(auth.internal)
        self.assertTrue(autonomous.is_autonomous(auth))

    def test_a_user_is_neither(self) -> None:
        auth = permissions.AuthContext(
            user=models.User(
                email='dev@example.com',
                display_name='Dev',
                is_active=True,
                is_admin=False,
                password_hash=password.hash_password('testpassword123'),
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            auth_method='jwt',
        )
        self.assertFalse(autonomous.is_userless(auth))
        self.assertFalse(autonomous.is_autonomous(auth))

    def test_internal_is_not_settable_from_a_payload_by_accident(
        self,
    ) -> None:
        """Defaults false, so every real authentication path leaves it so."""
        auth = permissions.AuthContext(auth_method='api_key')
        self.assertFalse(auth.internal)
