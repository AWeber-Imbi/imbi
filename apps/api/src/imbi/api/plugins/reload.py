"""Valkey pub/sub subscriber for cross-pod plugin reload.

The ``imbi:plugins:reload`` channel triggers in-process
``reload_plugins()`` on every subscriber. Anyone who can publish to
that channel can therefore re-import every installed plugin module —
so payloads are HMAC-signed with a key derived from ``jwt_secret``
(already required to be shared across pods) and the subscriber
rejects anything that doesn't verify or is older than
:data:`_MAX_AGE_SECONDS`.

Payload shape: ``"{unix_ts}:{nonce}:{hex_sig}"`` where ``hex_sig`` =
HMAC-SHA256(derived_key, ``"{unix_ts}:{nonce}"``).
"""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import secrets
import time
import typing
from collections.abc import AsyncGenerator

from valkey import asyncio as _valkey_asyncio

from imbi.api.plugins.lifecycle import audit_unavailable
from imbi.common import graph, valkey
from imbi.common.plugins.registry import (
    reload_plugins,
)

LOGGER = logging.getLogger(__name__)

_CHANNEL = 'imbi:plugins:reload'
_HMAC_INFO = b'imbi-plugin-reload-v1'
_MAX_AGE_SECONDS = 300


def _get_reload_key() -> bytes | None:
    """Derive the HMAC key from the auth ``jwt_secret``.

    Returns None when settings aren't loadable (e.g. import-time
    failures during test bootstrap), in which case publish/verify
    short-circuit to a hard failure.
    """
    try:
        from imbi.api.settings import get_auth_settings

        jwt_secret = get_auth_settings().jwt_secret
    except Exception:
        LOGGER.exception('Plugin reload: failed to load auth settings')
        return None
    if not jwt_secret:
        return None
    return hmac.new(jwt_secret.encode(), _HMAC_INFO, hashlib.sha256).digest()


def _sign(ts: int, nonce: str, key: bytes) -> str:
    return hmac.new(key, f'{ts}:{nonce}'.encode(), hashlib.sha256).hexdigest()


def _verify(
    payload: str, key: bytes, *, max_age: int = _MAX_AGE_SECONDS
) -> bool:
    parts = payload.split(':', 2)
    if len(parts) != 3:
        return False
    ts_str, nonce, sig = parts
    if not nonce:
        return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > max_age:
        return False
    return hmac.compare_digest(sig, _sign(ts, nonce, key))


async def _subscribe_reload(
    client: _valkey_asyncio.Valkey,
    db: graph.Graph,
    stop: asyncio.Event,
) -> None:
    pubsub = client.pubsub()
    await pubsub.subscribe(_CHANNEL)  # pyright: ignore[reportUnknownMemberType]
    LOGGER.info('Plugin reload subscriber started on channel %r', _CHANNEL)
    try:
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
                    pubsub.get_message(ignore_subscribe_messages=True),  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
                    timeout=1.0,
                )
            except TimeoutError:
                continue
            if msg is None:
                continue
            raw_data = typing.cast(
                'object',
                msg.get('data'),  # pyright: ignore[reportUnknownMemberType]
            )
            if isinstance(raw_data, (bytes, bytearray)):
                data = bytes(raw_data).decode('utf-8', errors='replace')
            elif isinstance(raw_data, str):
                data = raw_data
            else:
                LOGGER.warning(
                    'Plugin reload: ignoring non-string payload type %r',
                    type(raw_data).__name__,
                )
                continue
            key = _get_reload_key()
            if key is None:
                LOGGER.error(
                    'Plugin reload: HMAC key unavailable; dropping payload'
                )
                continue
            if not _verify(data, key):
                LOGGER.warning(
                    'Plugin reload: payload failed HMAC verification; dropping'
                )
                continue
            LOGGER.info('Plugin reload triggered via authenticated pub/sub')
            reload_plugins()
            await audit_unavailable(db)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(_CHANNEL)  # pyright: ignore[reportUnknownMemberType]


@contextlib.asynccontextmanager
async def plugin_reload_hook(
    db: graph.Graph | None = None,
) -> AsyncGenerator[None]:
    """Async context manager that runs the Valkey reload subscriber."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; plugin reload not started')
        yield
        return
    if db is None:
        LOGGER.warning('Graph not ready; plugin reload not started')
        yield
        return
    stop = asyncio.Event()
    task = asyncio.create_task(_subscribe_reload(client, db, stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def publish_reload(
    client: _valkey_asyncio.Valkey,
) -> None:
    """Publish a signed reload notification to all pods.

    Raises:
        RuntimeError: when the HMAC key cannot be derived (auth
            settings unloadable or ``jwt_secret`` empty).
    """
    key = _get_reload_key()
    if key is None:
        raise RuntimeError(
            'Cannot publish plugin-reload notification: '
            'jwt_secret is unavailable'
        )
    ts = int(time.time())
    nonce = secrets.token_urlsafe(16)
    payload = f'{ts}:{nonce}:{_sign(ts, nonce, key)}'
    await client.publish(  # pyright: ignore[reportUnknownMemberType]
        _CHANNEL, payload
    )
