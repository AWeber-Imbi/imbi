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
    )
    return jwt.encode(
        state_data.model_dump(),
        auth.jwt_secret,
        algorithm=auth.jwt_algorithm,
    )


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
    auth = auth_settings or settings.Auth()  # type: ignore[call-arg]
    try:
        payload = jwt.decode(
            state_token,
            auth.jwt_secret,
            algorithms=[auth.jwt_algorithm],
        )
        state_data = models.OAuthStateData(**payload)
    except jwt.InvalidTokenError as exc:
        raise ValueError(f'Invalid identity state token: {exc}') from exc
    if state_data.intent != 'identity' or not state_data.plugin_id:
        raise ValueError('State token is not for an identity flow')
    age = int(time.time()) - state_data.timestamp
    if age > max_age_seconds:
        raise ValueError(f'Identity state expired (age: {age}s)')
    return state_data
