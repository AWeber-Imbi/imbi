"""Identity-flow state JWT helpers.

Reuses the existing ``OAuthStateData`` model + JWT signing primitives
from :mod:`imbi_api.auth.oauth` so login and identity flows share one
state-token format.  ``intent='identity'`` discriminates the identity
flow path.
"""

import secrets
import time

import jwt

from imbi_api import settings
from imbi_api.auth import models


def encode_identity_state(
    *,
    plugin_id: str,
    plugin_slug: str,
    redirect_uri: str,
    intent: str = 'identity',
    return_to: str | None = None,
    code_verifier: str | None = None,
    actor_user_id: str | None = None,
    device_code: str | None = None,
    auth_settings: settings.Auth | None = None,
) -> str:
    """Encode the identity-flow state JWT and return the signed token."""
    auth = auth_settings or settings.Auth()  # type: ignore[call-arg]
    state_data = models.OAuthStateData(
        provider=plugin_slug,
        nonce=secrets.token_urlsafe(32),
        redirect_uri=redirect_uri,
        timestamp=int(time.time()),
        intent=intent,  # type: ignore[arg-type]
        plugin_id=plugin_id,
        code_verifier=code_verifier,
        return_to=return_to,
        actor_user_id=actor_user_id,
        device_code=device_code,
    )
    return jwt.encode(
        state_data.model_dump(),
        auth.jwt_secret,
        algorithm=auth.jwt_algorithm,
    )


def _decode_state_for_intent(
    state_token: str,
    *,
    expected_intent: str,
    invalid_message: str,
    intent_message: str,
    expired_label: str,
    auth_settings: settings.Auth | None = None,
    max_age_seconds: int = 600,
) -> models.OAuthStateData:
    """Shared decode + verify for identity-flow state JWTs.

    Both the ``identity`` and ``login`` intents use the same payload
    shape and the same expiry / plugin_id assertions; only the error
    messages differ. Centralizing the logic prevents the two flows from
    drifting apart over time.
    """
    auth = auth_settings or settings.Auth()  # type: ignore[call-arg]
    try:
        payload = jwt.decode(
            state_token,
            auth.jwt_secret,
            algorithms=[auth.jwt_algorithm],
        )
        state_data = models.OAuthStateData(**payload)
    except jwt.InvalidTokenError as exc:
        raise ValueError(f'{invalid_message}: {exc}') from exc
    if state_data.intent != expected_intent or not state_data.plugin_id:
        raise ValueError(intent_message)
    age = int(time.time()) - state_data.timestamp
    if age > max_age_seconds:
        raise ValueError(f'{expired_label} state expired (age: {age}s)')
    return state_data


def decode_identity_state(
    state_token: str,
    *,
    auth_settings: settings.Auth | None = None,
    max_age_seconds: int = 600,
) -> models.OAuthStateData:
    """Verify and decode an identity-flow state token.

    Raises :class:`ValueError` for invalid signature or expiry — same
    semantics as the login-side ``verify_oauth_state``.
    """
    return _decode_state_for_intent(
        state_token,
        expected_intent='identity',
        invalid_message='Invalid identity state token',
        intent_message='State token is not for an identity flow',
        expired_label='Identity',
        auth_settings=auth_settings,
        max_age_seconds=max_age_seconds,
    )


def decode_login_state(
    state_token: str,
    *,
    auth_settings: settings.Auth | None = None,
    max_age_seconds: int = 600,
) -> models.OAuthStateData:
    """Verify and decode an identity-plugin **login** state token.

    Mirrors :func:`decode_identity_state` but requires
    ``intent='login'``.
    """
    return _decode_state_for_intent(
        state_token,
        expected_intent='login',
        invalid_message='Invalid login state token',
        intent_message='State token is not for an identity-plugin login',
        expired_label='Login',
        auth_settings=auth_settings,
        max_age_seconds=max_age_seconds,
    )
