"""Background refresh sweeper for identity connections.

Polls :func:`stale_connections` every 60s, acquires a per-(user,
integration) Valkey lock to prevent thundering-herd on shared
dashboards, and calls :meth:`IdentityCapability.refresh` for each row
whose ``expires_at`` is within the next 5 minutes.  Failed refreshes
flip ``status='expired'``.

The actual lifespan integration lives in
:func:`imbi.api.lifespans.identity_refresh_hook`; this module only
exposes the loop body so it can be unit-tested without bringing the
full FastAPI app stack up.
"""

import asyncio
import datetime
import logging

import valkey.asyncio

from imbi.api.identity import errors, flows, repository
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
LOOKAHEAD_SECONDS = 300
# Lock long enough to cover a slow IdP roundtrip but never longer than
# the poll interval, so a stuck refresh can't permanently wedge the
# row out of the sweep rotation.
LOCK_TTL_SECONDS = 60


def _lock_key(integration_id: str, user_id: str) -> str:
    return f'imbi:identity:refresh:{integration_id}:{user_id}'


async def _try_lock(client: valkey.asyncio.Valkey, key: str) -> bool:
    """Acquire a Valkey ``SET NX EX 10`` lock; True on success."""
    try:
        result = await client.set(key, '1', nx=True, ex=LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        LOGGER.debug('Identity refresh lock acquire failed', exc_info=True)
        return False
    return bool(result)


async def _refresh_one(
    db: graph.Graph,
    client: valkey.asyncio.Valkey,
    row: dict[str, str],
) -> None:
    integration_id = row.get('integration_id') or ''
    user_id = row.get('user_id') or ''
    if not integration_id or not user_id:
        return
    if not await _try_lock(client, _lock_key(integration_id, user_id)):
        return
    try:
        await flows.refresh_connection(
            db, integration_id=integration_id, actor_user_id=user_id
        )
    except errors.IdentityRefreshFailed:
        # ``flows.refresh_connection`` flips status to ``expired`` only
        # for plugin-level refresh failures; the missing-refresh-token
        # branch raises before reaching that code path.  Mark the
        # connection here so we do not retry it every poll.  Guard the
        # lookup so a transient graph error does not abort the sweeper
        # iteration over remaining rows.
        try:
            connection = await repository.load_connection(
                db, integration_id, user_id
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Failed to load identity connection after refresh '
                'failure integration_id=%s user_id=%s',
                integration_id,
                user_id,
                exc_info=True,
            )
            return
        if connection is not None and connection.status != 'expired':
            try:
                await repository.mark_status(
                    db, connection.connection_id, 'expired'
                )
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    'Failed to mark identity connection expired '
                    'integration_id=%s user_id=%s',
                    integration_id,
                    user_id,
                    exc_info=True,
                )
        LOGGER.warning(
            'Identity refresh failed integration_id=%s user_id=%s; '
            'connection marked expired',
            integration_id,
            user_id,
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Identity refresh raised integration_id=%s user_id=%s',
            integration_id,
            user_id,
            exc_info=True,
        )


async def run_sweeper(
    db: graph.Graph,
    client: valkey.asyncio.Valkey,
    *,
    stop: asyncio.Event,
) -> None:
    """Run the sweeper loop until ``stop`` is set."""
    LOGGER.info('Identity refresh sweeper starting')
    while not stop.is_set():
        try:
            horizon = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                seconds=LOOKAHEAD_SECONDS
            )
            rows = await repository.stale_connections(db, horizon)
            for row in rows:
                if stop.is_set():
                    break
                await _refresh_one(db, client, row)
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Identity refresh sweeper iteration failed', exc_info=True
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            continue
    LOGGER.info('Identity refresh sweeper stopped')
