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

import httpx

from imbi.scheduler import identity, models, render, runs, settings

LOGGER = logging.getLogger(__name__)

RETRYABLE_CLIENT_STATUS = 429

HTTP_INTERNAL_SERVER_ERROR = 500


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
        trace_id: str = '',
    ) -> runs.Run:
        """Fire `task` once, honoring its retry policy."""
        actor = self._resolver.actor_name(task)
        run = runs.start(task, fired_at, actor_name=actor, trace_id=trace_id)
        try:
            bearer = await self._resolver.bearer(task)
        except identity.IdentityError as err:
            LOGGER.info('Skipping %s: %s', task.slug, err.reason)
            return runs.skipped(
                task,
                fired_at,
                err.reason,
                actor_name=actor,
                trace_id=trace_id,
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
                    task, task.target, renderer, self._settings.api_url
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
        for attempt in range(1, attempts + 1):
            current = run.model_copy(update={'attempt': attempt})
            result = await self._attempt(task, current, request, bearer)
            if not _is_retryable(result):
                return result
            if attempt < attempts:
                await asyncio.sleep(_backoff(task, attempt))
        return result

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
