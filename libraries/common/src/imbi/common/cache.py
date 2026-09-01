"""In-process bounded caching primitives.

Several call sites across the platform need the same small thing: a
process-local cache that cannot grow without bound and whose entries go
stale. Each had grown its own ``OrderedDict`` and its own expiry policy
-- uniform TTL in :mod:`imbi.common.auth.permissions` and
:mod:`imbi.common.mcp`, no expiry at all in :mod:`imbi.common.access_log`
and the GitHub commit plugin, and per-entry deadlines (GitHub's own
``expires_at``) in the GitHub App token cache. :class:`LRUCache` covers
all of them with one knob each: an instance ``ttl`` that every entry
inherits, and a per-``set`` ``expires_at`` that overrides it.

The cache is deliberately **synchronous**. ``access_log`` resolves the
API-key owner from inside the ASGI response path and cannot await, so an
``asyncio.Lock`` in the cache would lock that caller out. Where
concurrent producers must be serialized -- to keep N simultaneous misses
from all doing the same expensive work -- use :class:`KeyedLock` around
the check/produce/store section instead, which keeps the lock's purpose
legible and the cache usable from sync code.

Everything here is per-process by design. These caches hold bearer
secrets and auth contexts; a shared backing store would put them at rest
somewhere else to save a round trip.
"""

import asyncio
import collections
import collections.abc
import contextlib
import time

__all__ = ['KeyedLock', 'LRUCache']


class LRUCache[K, V]:
    """A bounded, optionally expiring, least-recently-used cache.

    Reads and writes both refresh an entry's recency, so the entry
    evicted at capacity is the one untouched for longest. Expiry is
    lazy: an entry past its deadline is dropped when it is next looked
    up rather than by a sweeper.

    Args:
        max_entries: Upper bound on live entries. Inserting past it
            evicts the least recently used.
        ttl: Seconds an entry stays usable, applied to every ``set``
            that does not carry its own ``expires_at``. ``None`` (the
            default) means entries never expire on their own and only
            leave via eviction, :meth:`pop`, or :meth:`clear`.

    """

    def __init__(self, max_entries: int, *, ttl: float | None = None) -> None:
        if max_entries < 1:
            raise ValueError('max_entries must be at least 1')
        self._entries: collections.OrderedDict[K, tuple[float | None, V]] = (
            collections.OrderedDict()
        )
        self._max_entries = max_entries
        self._ttl = ttl

    def __len__(self) -> int:
        """Return the number of entries, including any not yet reaped."""
        return len(self._entries)

    def __contains__(self, key: K) -> bool:
        """Return whether a live (unexpired) entry exists for ``key``.

        Membership does not refresh recency -- asking whether something
        is cached is not the same as using it.
        """
        entry = self._entries.get(key)
        return entry is not None and (
            entry[0] is None or entry[0] >= time.monotonic()
        )

    def get(self, key: K) -> V | None:
        """Return the cached value, or ``None`` if absent or expired.

        A ``None`` value cannot be distinguished from a miss, so callers
        that need to memoize "no result" should cache a sentinel.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and time.monotonic() > expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def set(
        self, key: K, value: V, *, expires_at: float | None = None
    ) -> None:
        """Store a value, evicting the least recently used at capacity.

        Args:
            key: Cache key.
            value: Value to store.
            expires_at: A :func:`time.monotonic` instant after which the
                entry is stale, overriding the instance ``ttl``. Pass it
                when the deadline comes from outside -- an upstream
                token expiry, say -- rather than from a fixed lifetime.
                Omitting it means "use the instance policy", so a cache
                built with a ``ttl`` cannot be given a single entry that
                outlives it; pass a distant ``expires_at`` if you ever
                need that.

        """
        if expires_at is None and self._ttl is not None:
            expires_at = time.monotonic() + self._ttl
        self._entries[key] = (expires_at, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def pop(self, key: K) -> V | None:
        """Remove a key, returning its value if one was cached.

        An expired entry reports as a miss, matching :meth:`get`.
        """
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and time.monotonic() > expires_at:
            return None
        return value

    def clear(self) -> None:
        """Drop every entry."""
        self._entries.clear()


class KeyedLock[K]:
    """Serialize concurrent async work per key.

    Guards a check/produce/store section so that N coroutines arriving
    on the same cold cache key do the expensive work once and the rest
    wait, then read what the winner stored::

        async with locks(key):
            if (hit := cache.get(key)) is not None:
                return hit
            value = await produce()
            cache.set(key, value)

    Locks are created on demand and dropped once no coroutine holds or
    awaits them, so the dictionary tracks in-flight work rather than
    every key ever seen. Different keys never block each other.
    """

    def __init__(self) -> None:
        self._locks: dict[K, asyncio.Lock] = {}
        self._waiters: collections.Counter[K] = collections.Counter()

    def __len__(self) -> int:
        """Return the number of keys with work in flight."""
        return len(self._locks)

    @contextlib.asynccontextmanager
    async def __call__(self, key: K) -> collections.abc.AsyncIterator[None]:
        """Hold the lock for ``key`` for the duration of the block."""
        lock = self._locks.get(key)
        if lock is None:
            # No await between the miss and the store, so two coroutines
            # cannot both create a lock for the same key.
            lock = self._locks[key] = asyncio.Lock()
        self._waiters[key] += 1
        try:
            async with lock:
                yield
        finally:
            self._waiters[key] -= 1
            if not self._waiters[key]:
                del self._waiters[key]
                del self._locks[key]
