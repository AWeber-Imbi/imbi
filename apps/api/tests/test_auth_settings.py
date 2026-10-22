"""Verify the IMBI_AUTH_PASSWORD_* and IMBI_AUTH_RATE_LIMIT_* settings
are read at request time."""

import unittest
from unittest import mock

import fastapi
import pydantic

from imbi.api import settings
from imbi.api.domain import models
from imbi.api.endpoints import auth
from imbi.api.middleware import rate_limit


def _patch_auth(**overrides: object) -> mock._patch[mock.MagicMock]:
    return mock.patch.object(
        settings,
        'get_auth_settings',
        return_value=settings.Auth(**overrides),
    )


class PasswordPolicyTestCase(unittest.TestCase):
    def test_default_policy_rejects_weak_password(self) -> None:
        with _patch_auth(), self.assertRaises(pydantic.ValidationError):
            models.PasswordChangeRequest(new_password='short')

    def test_settings_relax_policy(self) -> None:
        with _patch_auth(
            password_min_length=4,
            password_require_uppercase=False,
            password_require_digit=False,
            password_require_special=False,
        ):
            request = models.PasswordChangeRequest(new_password='abcd')
        self.assertEqual(request.new_password, 'abcd')

    def test_settings_raise_min_length(self) -> None:
        with (
            _patch_auth(password_min_length=20),
            self.assertRaisesRegex(pydantic.ValidationError, '20 characters'),
        ):
            models.PasswordChangeRequest(new_password='SecurePass123!@#')

    def test_user_create_applies_policy(self) -> None:
        fields = {
            'email': 'u@example.com',
            'display_name': 'U',
            'organization_slug': 'o',
            'role_slug': 'r',
        }
        with _patch_auth():
            models.UserCreate(**fields)
            models.UserCreate(**fields, password='SecurePass123!@#')
            with self.assertRaises(pydantic.ValidationError):
                models.UserCreate(**fields, password='weak')


class RateLimitSettingsTestCase(unittest.TestCase):
    def _limits(self, endpoint: str) -> list[str]:
        groups = rate_limit.limiter._dynamic_route_limits[
            f'{auth.__name__}.{endpoint}'
        ]
        return [str(limit.limit) for group in groups for limit in group]

    def test_defaults_match_previous_hardcoded_values(self) -> None:
        with _patch_auth():
            self.assertEqual(self._limits('login'), ['5 per 1 minute'])
            self.assertEqual(
                self._limits('refresh_token'), ['10 per 1 minute']
            )
            self.assertEqual(self._limits('oauth_login'), ['3 per 1 minute'])

    def test_settings_override_limits(self) -> None:
        with _patch_auth(
            rate_limit_login='1/second',
            rate_limit_token_refresh='2/hour',
            rate_limit_oauth_init='7/day',
        ):
            self.assertEqual(self._limits('login'), ['1 per 1 second'])
            self.assertEqual(self._limits('refresh_token'), ['2 per 1 hour'])
            self.assertEqual(self._limits('oauth_login'), ['7 per 1 day'])

    def test_invalid_limit_is_rejected(self) -> None:
        for field in (
            'rate_limit_login',
            'rate_limit_token_refresh',
            'rate_limit_oauth_init',
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(pydantic.ValidationError),
            ):
                settings.Auth(**{field: '5/minutes-ish'})


class RefreshGrantRateLimitTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        rate_limit.limiter.reset()
        self.addCleanup(rate_limit.limiter.reset)

    async def test_refresh_grant_uses_refresh_limit(self) -> None:
        request = fastapi.Request(
            {'type': 'http', 'client': ('203.0.113.9', 1), 'headers': []}
        )
        with _patch_auth(rate_limit_token_refresh='1/minute'):
            with self.assertRaises(fastapi.HTTPException) as first:
                await auth._refresh_token_grant(request, mock.Mock(), None)
            self.assertEqual(first.exception.status_code, 400)
            with self.assertRaises(fastapi.HTTPException) as second:
                await auth._refresh_token_grant(request, mock.Mock(), None)
            self.assertEqual(second.exception.status_code, 429)
