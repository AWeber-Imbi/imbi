"""A setup secret that the runner holds in memory and renews (WIF plan
4.6 and 4.7): the model key and each MCP header secret (ADR 0031).

The renewal rules are a copy of TokenCache in
``imbi/common/llm/tokens.py``. The harness must not depend on
imbi-common (see pyproject.toml), so keep the two in step.
"""

import asyncio
import datetime
import logging
import random
import typing

from imbi.harness import proxy

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: The longest refresh lead of an access token (WIF plan 4.6).
REFRESH_LEAD = 300.0
#: The longest wait between two failed renewals.
RETRY_MAX = 30.0
#: The shortest wait between two successful renewals.
RENEW_MIN = 30.0


class Refresher:
    """The current value of one secret. A static secret is fetched once;
    a dynamic one (with ``expires_at``) is renewed before it expires and
    after a ``401``.

    Args:
        fetch: Gets the secret from the secrets broker.
        name: The secret in log messages.
        owner: The task in log messages.
        errors: The errors of ``fetch`` that a background renewal
            retries.

    """

    def __init__(
        self,
        fetch: abc.Callable[[], abc.Awaitable[proxy.Credential]],
        name: str,
        owner: str,
        errors: tuple[type[Exception], ...],
    ) -> None:
        self.fetch = fetch
        self.name = name
        self.owner = owner
        self.errors = errors
        self.credential = proxy.Credential('')
        #: One renewal at a time; a second caller waits for it.
        self.lock = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Fetch the secret, and renew it in the background when it has
        an expiry. Raises what ``fetch`` raises."""
        self.credential = await self.fetch()
        if self.credential.expires_at is not None:
            self.task = asyncio.create_task(self._refresh())

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def renew(self, failed: str | None = None) -> None:
        """Replace a dynamic secret. With ``failed``, only when that value
        is still the current one (another caller can have replaced it).
        A call in progress keeps the old value. Raises what ``fetch``
        raises."""
        async with self.lock:
            if self.credential.expires_at is None or (
                failed is not None and failed != self.credential.value
            ):
                return
            self.credential = await self.fetch()

    async def _refresh(self) -> None:
        """Renew the secret before it expires: at the lesser of
        :data:`REFRESH_LEAD` and 20 percent of its lifetime before the
        expiry, with a jitter of at most half of that lead. Retry a
        failed renewal with bounded backoff. Wait at least
        :data:`RENEW_MIN` after a renewal, also when the new value is
        near its expiry. :meth:`stop` ends it."""
        floor = 0.0
        while (expires_at := self.credential.expires_at) is not None:
            lifetime = (
                expires_at - datetime.datetime.now(datetime.UTC)
            ).total_seconds()
            lead = min(REFRESH_LEAD, 0.2 * max(lifetime, 0.0))
            await asyncio.sleep(
                max(lifetime - lead - random.uniform(0, lead / 2), floor)  # noqa: S311 - jitter, not a secret
            )
            floor = RENEW_MIN
            delay = 1.0
            while self.credential.expires_at == expires_at:
                try:
                    await self.renew()
                    break  # same expiry: the outer loop waits the floor
                except self.errors as error:
                    LOGGER.warning(
                        '%s renewal of %s failed: %s',
                        self.name,
                        self.owner,
                        error,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, RETRY_MAX)
