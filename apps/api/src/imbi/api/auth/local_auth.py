"""Local password authentication configuration repository.

Reads/writes the singleton ``LocalAuthConfig`` node in the graph.
A small in-memory TTL cache keeps the ``/auth/providers`` hot path
off the graph.  Writes invalidate the cache.
"""

from __future__ import annotations

import datetime
import logging
import time

from imbi_common import graph

from imbi_api.domain import models

LOGGER = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0
_CACHE_KEY = 'global'

_config_cache: dict[str, tuple[models.LocalAuthConfig, float]] = {}


def _invalidate_cache() -> None:
    """Drop the cached config entry."""
    _config_cache.clear()


async def get_config(db: graph.Graph) -> models.LocalAuthConfig:
    """Return the local-auth config, defaulting to enabled.

    If no row exists yet a default ``LocalAuthConfig(enabled=True)`` is
    returned without persisting it (lazy-default semantics).
    """
    cached = _config_cache.get(_CACHE_KEY)
    now = time.time()
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    rows = await db.match(models.LocalAuthConfig, {'key': 'global'})
    config = rows[0] if rows else models.LocalAuthConfig(enabled=True)
    _config_cache[_CACHE_KEY] = (config, now)
    return config


async def set_enabled(
    db: graph.Graph, enabled: bool
) -> models.LocalAuthConfig:
    """Persist the singleton config and invalidate the cache."""
    config = models.LocalAuthConfig(
        enabled=enabled,
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    await db.merge(config, ['key'])
    _invalidate_cache()
    return config
