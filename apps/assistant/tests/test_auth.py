"""Tests for the assistant's auth re-exports.

The JWT verification, principal loading, and permission query this
module used to own now live in :mod:`imbi.common.auth.permissions`, and
their cases live in ``libraries/common/tests/auth/``. What is worth
testing here is the seam: that the names the endpoints import still
resolve, and that they resolve to the shared implementation rather than
to a copy that could drift.
"""

import unittest

import fastapi

from imbi.assistant import auth
from imbi.common import models
from imbi.common.auth import permissions


class ReExportTestCase(unittest.TestCase):
    """The endpoints import these names from ``assistant.auth``."""

    def test_auth_context_is_the_shared_one(self) -> None:
        self.assertIs(auth.AuthContext, permissions.AuthContext)

    def test_user_is_the_shared_model(self) -> None:
        self.assertIs(auth.User, models.User)

    def test_get_current_user_is_the_shared_dependency(self) -> None:
        self.assertIs(auth.get_current_user, permissions.get_current_user)

    def test_oauth2_scheme_is_the_shared_scheme(self) -> None:
        self.assertIs(auth.oauth2_scheme, permissions.oauth2_scheme)

    def test_permission_loader_is_the_shared_query(self) -> None:
        self.assertIs(
            auth.load_principal_permissions,
            permissions.load_principal_permissions,
        )

    def test_every_exported_name_exists(self) -> None:
        for name in auth.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(auth, name))


class ServiceAccountContextTestCase(unittest.TestCase):
    """A service-account caller has no ``user``.

    Accepting client-credentials tokens is new here -- the local
    implementation only ever built a context from a user JWT. The
    endpoints reach for ``require_user``, which raises 403 rather than
    returning None, so this is the behavior that keeps a service-account
    token out of code that assumes a person.
    """

    def _context(self) -> auth.AuthContext:
        return auth.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-scheduler', display_name='Scheduler'
            ),
            auth_method='client_credentials',
        )

    def test_require_user_rejects_a_service_account(self) -> None:
        ctx = self._context()
        self.assertIsNone(ctx.user)
        with self.assertRaises(fastapi.HTTPException) as caught:
            _ = ctx.require_user
        self.assertEqual(caught.exception.status_code, 403)

    def test_principal_name_falls_back_to_the_slug(self) -> None:
        self.assertEqual(self._context().principal_name, 'imbi-scheduler')

    def test_a_service_account_is_not_an_admin(self) -> None:
        self.assertFalse(self._context().is_admin)
