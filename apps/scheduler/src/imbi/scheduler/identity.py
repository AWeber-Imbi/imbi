"""Identity resolution.

Resolved at fire time, never at creation time: a task stores *who* it runs as,
and the credential is obtained fresh for each run. That is what makes revoking
consent or deactivating a user take effect without touching the task.

Phase 1 supports service-account identity. Delegated (run-as-user) identity
needs the RFC 8693 token-exchange grant that ADR 0016 specifies and `imbi-api`
does not implement yet; there is deliberately no local-minting fallback (ADR
0003), so a delegated task is refused rather than run under a lie.
"""

import asyncio
import datetime
import logging

import httpx

from imbi.scheduler import models, settings

LOGGER = logging.getLogger(__name__)

#: Refresh a service-account token this long before it expires, so a run never
#: starts with a credential about to lapse mid-flight.
REFRESH_MARGIN = datetime.timedelta(seconds=60)

TOKEN_PATH = '/auth/token'

HTTP_OK = 200

#: Fallback lifetime when the token response omits `expires_in`.
DEFAULT_TOKEN_LIFETIME = 900


class IdentityError(Exception):
    """Identity could not be resolved.

    Raised rather than returned because every caller must treat it the same
    way: record a `skipped` run with the reason and leave retries untouched.
    A task whose principal cannot be established has not failed — it should
    stop quietly.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ServiceAccountToken:
    """Caches the scheduler's own client-credential token.

    One token serves every system task, refreshed proactively rather than on
    a 401, mirroring the `_AuthManager` pattern ADR 0016 cites.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: settings.Scheduler | None = None,
    ) -> None:
        self._client = client
        self._settings = config or settings.Scheduler()
        self._token: str | None = None
        self._expires_at: datetime.datetime | None = None
        #: Serializes refreshes so a cold cache under concurrent firings
        #: makes one token request rather than one per run.
        self._lock = asyncio.Lock()

    def _is_fresh(self, now: datetime.datetime) -> bool:
        return (
            self._expires_at is not None
            and now + REFRESH_MARGIN < self._expires_at
        )

    async def token(self) -> str:
        """Return a valid access token, fetching one if needed."""
        now = datetime.datetime.now(datetime.UTC)
        if self._token is not None and self._is_fresh(now):
            return self._token
        async with self._lock:
            # Re-check: a firing that queued behind the lock is served by
            # whichever one did the fetch.
            now = datetime.datetime.now(datetime.UTC)
            if self._token is not None and self._is_fresh(now):
                return self._token
            return await self._fetch(now)

    async def _fetch(self, now: datetime.datetime) -> str:
        if not (
            self._settings.sa_client_id and self._settings.sa_client_secret
        ):
            raise IdentityError(
                'scheduler service account is not configured '
                '(IMBI_SCHEDULER_SA_CLIENT_ID / _SECRET)'
            )
        url = self._settings.api_url.rstrip('/') + TOKEN_PATH
        try:
            response = await self._client.post(
                url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self._settings.sa_client_id,
                    'client_secret': self._settings.sa_client_secret,
                },
            )
        except httpx.HTTPError as err:
            raise IdentityError(
                f'service account token request failed: {err}'
            ) from err
        if response.status_code != HTTP_OK:
            raise IdentityError(
                'service account token request returned '
                f'{response.status_code}'
            )
        payload = response.json()
        token: str | None = payload.get('access_token')
        if not token:
            raise IdentityError('token response carried no access_token')
        self._token = token
        self._expires_at = now + datetime.timedelta(
            seconds=int(payload.get('expires_in', DEFAULT_TOKEN_LIFETIME))
        )
        LOGGER.debug(
            'Service account token refreshed, valid until %s', self._expires_at
        )
        return token

    def invalidate(self) -> None:
        """Discard the cached token so the next call re-fetches."""
        self._token = None
        self._expires_at = None


class Resolver:
    """Turns a task's identity into a bearer token for its run."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: settings.Scheduler | None = None,
    ) -> None:
        self._settings = config or settings.Scheduler()
        self.service_account = ServiceAccountToken(client, self._settings)

    async def bearer(self, task: models.Task) -> str | None:
        """Return the bearer token for `task`, or None if it needs none.

        Gateway targets need none: the endpoint has no bearer check and
        derives attribution from the payload, so attaching a credential would
        be theater.
        """
        if task.identity is None:
            return None
        if task.identity.kind == 'service_account':
            return await self._service_account_bearer(task.identity)
        return await self._delegated_bearer(task.identity)

    async def _service_account_bearer(self, identity: models.Identity) -> str:
        if identity.subject != self._settings.sa_slug:
            raise IdentityError(
                f'cannot run as service account {identity.subject!r}: '
                "only the scheduler's own service account is available "
                '(see ADR 0002)'
            )
        return await self.service_account.token()

    async def _delegated_bearer(self, identity: models.Identity) -> str:
        raise IdentityError(
            f'delegated execution as {identity.subject!r} requires the '
            'token-exchange grant from ADR 0016, which imbi-api does not '
            'implement yet'
        )

    def actor_name(self, task: models.Task) -> str:
        """Return the actor behind a delegated run, for attribution."""
        if task.identity is not None and (
            task.identity.kind == 'delegated_user'
        ):
            return self._settings.sa_slug
        return ''
