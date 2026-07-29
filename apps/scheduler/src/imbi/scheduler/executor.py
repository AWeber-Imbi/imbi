"""Run execution.

One firing is one HTTP call. There is no dispatch-and-reconcile machinery and
no callback endpoint: the scheduler triggers, classifies what came back, and
records it.

Classification is where the judgment lives. In particular a gateway 204 is
`no_effect`, not success — the delivery was accepted and then dropped (no
matching webhook, no project resolved, no rule matched), and calling that a
success would hide a task that silently does nothing forever.
"""

import asyncio
import datetime
import logging
import typing
import uuid

import httpx
import pydantic

from imbi.scheduler import identity, models, render, runs, settings

LOGGER = logging.getLogger(__name__)

RETRYABLE_CLIENT_STATUS = 429

HTTP_UNAUTHORIZED = 401

HTTP_INTERNAL_SERVER_ERROR = 500


class DryRun(pydantic.BaseModel):
    """What a firing *would* do, without doing it.

    Both failure modes a task can have before it ever reaches the network are
    reported rather than raised: an identity that will not resolve and a
    template that will not render are exactly what an operator is debugging,
    and a 500 would tell them less than the reason does.

    ``bearer_resolved`` rather than the credential itself -- a debugging
    endpoint that echoes a live token back over HTTP would be a credential
    leak, and knowing whether resolution succeeded is the diagnostic.
    """

    would_run: bool
    method: str = ''
    url: str = ''
    query: dict[str, str] = {}
    body: dict[str, typing.Any] | None = None
    headers: dict[str, str] = {}
    identity_kind: str = ''
    principal_name: str = ''
    actor_name: str = ''
    bearer_resolved: bool = False
    reason: str = ''


class Executor:
    """Executes one task firing and returns the recorded run."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        resolver: identity.Resolver,
        config: settings.Scheduler | None = None,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._settings = config or settings.Scheduler()

    async def execute(
        self,
        task: models.Task,
        fired_at: datetime.datetime,
        *,
        run_id: uuid.UUID | None = None,
        trace_id: str = '',
    ) -> runs.Run:
        """Fire `task` once, honoring its retry policy.

        The `running` row is written before anything is attempted, and the
        caller writes the terminal row over it. Two writes rather than one so
        that an in-flight run is visible while it runs, and so a replica
        killed mid-run leaves the firing in history instead of leaving no
        trace that it ever happened.
        """
        actor = self._resolver.actor_name(task)
        run = runs.start(
            task,
            fired_at,
            run_id=run_id,
            actor_name=actor,
            trace_id=trace_id,
        )
        await runs.record(run)
        try:
            bearer = await self._resolver.bearer(task)
        except identity.IdentityError as err:
            LOGGER.info('Skipping %s: %s', task.slug, err.reason)
            return runs.finish(
                run,
                'skipped',
                runs.Outcome(error_type='skipped', error_message=err.reason),
                finished_at=fired_at,
            )
        try:
            request = self._render(task, run.run_id, fired_at)
        except render.RenderError as err:
            return runs.finish(
                run,
                'failed',
                runs.Outcome(error_type='render', error_message=str(err)),
            )
        return await self._attempt_with_retries(task, run, request, bearer)

    async def dry_run(
        self,
        task: models.Task,
        fired_at: datetime.datetime,
    ) -> DryRun:
        """Resolve identity and render the target without calling it.

        Deliberately shares :meth:`_render` and the resolver with
        :meth:`execute`: a dry run that built the request its own way could
        agree with the real path right up to the moment it stopped being
        useful. Nothing is recorded — a dry run is not a firing, and putting
        one in history would corrupt the outcome counters.
        """
        actor = self._resolver.actor_name(task)
        identity_kind = task.identity.kind if task.identity else 'none'
        base = DryRun(
            would_run=False,
            identity_kind=identity_kind,
            principal_name=task.principal_name,
            actor_name=actor,
        )
        try:
            bearer = await self._resolver.bearer(task)
        except identity.IdentityError as err:
            return base.model_copy(update={'reason': err.reason})
        try:
            request = self._render(task, str(uuid.uuid4()), fired_at)
        except render.RenderError as err:
            return base.model_copy(
                update={
                    'bearer_resolved': bearer is not None,
                    'reason': f'render failed: {err}',
                }
            )
        headers = dict(request.headers)
        if bearer:
            headers['Authorization'] = 'Bearer <redacted>'
        return base.model_copy(
            update={
                'would_run': True,
                'method': request.method,
                'url': request.url,
                'query': request.query,
                'body': request.body,
                'headers': headers,
                'bearer_resolved': bearer is not None,
            }
        )

    def _render(
        self,
        task: models.Task,
        run_id: str,
        fired_at: datetime.datetime,
    ) -> render.RenderedRequest:
        renderer = render.Renderer(render.context(task, fired_at, run_id))
        # Exhaustive rather than if/else: a new target kind must fail loudly
        # here instead of falling through to a gateway delivery.
        match task.target:
            case models.ApiTarget():
                request = render.api_request(
                    task, task.target, renderer, self._settings.api_base_url
                )
            case models.GatewayTarget():
                request = render.gateway_request(
                    task.target, renderer, self._settings.gateway_url
                )
            case _:  # pragma: no cover - the union is closed
                typing.assert_never(task.target)
        if task.execution.idempotency_key:
            headers = dict(request.headers)
            headers['Idempotency-Key'] = renderer.text(
                task.execution.idempotency_key
            )
            request = request._replace(headers=headers)
        return request

    async def _attempt_with_retries(
        self,
        task: models.Task,
        run: runs.Run,
        request: render.RenderedRequest,
        bearer: str | None,
    ) -> runs.Run:
        attempts = task.execution.retries + 1
        result = run
        reauthed = False
        attempt = 1
        while attempt <= attempts:
            current = run.model_copy(update={'attempt': attempt})
            result = await self._attempt(task, current, request, bearer)
            if self._needs_reauth(result, bearer, reauthed=reauthed):
                reauthed = True
                try:
                    bearer = await self._reauthenticate(task)
                except identity.IdentityError as err:
                    return runs.finish(
                        current,
                        'skipped',
                        runs.Outcome(
                            error_type='skipped', error_message=err.reason
                        ),
                    )
                continue
            if not _is_retryable(result):
                return result
            if attempt < attempts:
                await asyncio.sleep(_backoff(task, attempt))
            attempt += 1
        return result

    def _needs_reauth(
        self, result: runs.Run, bearer: str | None, *, reauthed: bool
    ) -> bool:
        """Return whether a 401 earns one more try under a fresh credential.

        Exactly one, and it does not consume a retry: a rotated secret should
        cost a token request, not the task's whole retry budget. A second 401
        is the target's answer about the permission rather than the
        credential.
        """
        return (
            not reauthed
            and bearer is not None
            and result.http_status == HTTP_UNAUTHORIZED
        )

    async def _reauthenticate(self, task: models.Task) -> str | None:
        """Discard the cached credential and resolve a new one."""
        LOGGER.info('Re-authenticating after a 401 firing %s', task.slug)
        self._resolver.invalidate(task)
        return await self._resolver.bearer(task)

    async def _attempt(
        self,
        task: models.Task,
        run: runs.Run,
        request: render.RenderedRequest,
        bearer: str | None,
    ) -> runs.Run:
        headers = dict(request.headers)
        if bearer:
            headers['Authorization'] = f'Bearer {bearer}'
        try:
            response = await self._client.request(
                request.method,
                request.url,
                params=request.query or None,
                json=request.body,
                headers=headers,
                timeout=task.execution.timeout,
            )
        except httpx.TimeoutException as err:
            return runs.finish(
                run,
                'timed_out',
                runs.Outcome(error_type='timeout', error_message=str(err)),
            )
        except httpx.HTTPError as err:
            return runs.finish(
                run,
                'failed',
                runs.Outcome(error_type='transport', error_message=str(err)),
            )
        return runs.finish(
            run,
            task.target.classify(response),
            runs.Outcome(
                http_status=response.status_code,
                response=response.text,
                error_type=(
                    ''
                    if response.is_success
                    else f'http_{response.status_code}'
                ),
            ),
        )


def _is_retryable(run: runs.Run) -> bool:
    """Return whether another attempt could plausibly succeed.

    A 4xx other than 429 is the request's own fault, so replaying it wastes a
    call and muddies the history.
    """
    if run.state in {'succeeded', 'no_effect', 'skipped'}:
        return False
    if run.state == 'timed_out':
        return True
    if run.http_status == 0:
        return True
    if run.http_status == RETRYABLE_CLIENT_STATUS:
        return True
    return run.http_status >= HTTP_INTERNAL_SERVER_ERROR


def _backoff(task: models.Task, attempt: int) -> float:
    """Return the delay before the next attempt, in seconds."""
    if task.execution.retry_backoff == 'none':
        return 0.0
    if task.execution.retry_backoff == 'linear':
        return float(attempt)
    return float(2 ** (attempt - 1))
