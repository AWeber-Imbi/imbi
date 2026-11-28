"""Step executors (ADR 0021).

Each executor runs one call of one step and returns an
:class:`Outcome`. A step that spans claims (a wait, a deployment that
rolls out) returns ``resume_at`` and its progress in ``state``; the
engine calls it again with that state when the run is due.

Deploy, release, rollback, email, and Slack go through imbi-api as the
``imbi-workflows`` service account, so the bounds of ADR 0017 apply to
deployments, imbi-api sends email only to users and teams of the
organization, and only imbi-api holds the Slack bot token. They send
the idempotency key ``<run_id>:<node_key>``: after a crash the engine
calls them again, and imbi-api returns the first result instead of
acting again, or ``409 outcome_unknown``.

An agent step asks imbi-api for the agent task of the step: imbi-api
makes it with the key ``<run_id>:<node_key>`` the first time, and
returns it after that. The step polls it until it is closed.

A script step runs its code in the sandbox of
:mod:`imbi.common.workflows.script_runner` (ADR 0027).

An LLM Call step asks imbi-api to run its saved prompt, with the key
``<run_id>:<node_key>:<attempt>``. imbi-api records each model call
with the key, so a repeat of an attempt (after a crash) gets the first
answer and makes no second call. A retry after a known failure is a
new attempt and a new call. A retry after a timeout sends the key of
the earlier attempt again: imbi-api returns the outcome of that call.
"""

import asyncio
import dataclasses
import datetime
import logging
import math
import re
import typing
import urllib.parse
import uuid

import httpx
import psycopg
import pydantic

from imbi.common import graph, versioning
from imbi.common.auth import encryption
from imbi.common.llm import drivers, typesafe
from imbi.common.plugins import base
from imbi.common.workflows import graph as wf
from imbi.common.workflows import registry, script_runner, step_type
from imbi.common.workflows.registry import (
    agent,
    assign_ticket,
    condition,
    deploy,
    email,
    llm_call,
    model_decision,
    release,
    rollback,
    script,
    search_logs,
    slack,
    wait,
)
from imbi.workflows import settings

LOGGER = logging.getLogger(__name__)

#: Parameters can come from a trigger payload, so the values that name
#: a path or a ref are checked before a call, and every path segment is
#: quoted. A project and an environment are an id or a slug; a version
#: is a tag or a commit, with no ``/`` and no ``..``.
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
_REF = re.compile(r'^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$')

_DURATION = re.compile(rf'^{wait.DURATION}$')
_UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}

#: Statuses of a deployment run that end it, and the port they take.
_DEPLOYMENT_PORTS = {'success': 0, 'failure': 1, 'cancelled': 1}
#: The same for the status of a ``Deployment`` node.
_DEPLOYMENT_NODE_PORTS = {'success': 0, 'failed': 1, 'rolled_back': 1}

HTTP_OK = 200
HTTP_CLIENT_ERROR = 400
HTTP_FORBIDDEN = 403
HTTP_SERVER_ERROR = 500

#: Seconds that the engine waits for the answer of an LLM Call step.
#: More than the time after which imbi-api stops a call (its provider
#: timeout, 120 seconds, plus the render and a token), so imbi-api
#: always answers first.
LLM_CALL_TIMEOUT = 190.0
#: Seconds before the engine asks again for the answer of an LLM Call
#: step that imbi-api still runs.
LLM_CALL_POLL_SECONDS = 15
#: Seconds before the engine asks again for the answer of a plugin step
#: call that imbi-api still runs (ADR 0032).
PLUGIN_CALL_POLL_SECONDS = 15


class StepError(Exception):
    """A step call failed. ``code`` is stored as the step's error.

    ``unreachable`` marks a call that did not get an HTTP response from
    imbi-api at all, such as a connection refused while imbi-api
    restarts. The engine waits longer before it retries such a call.
    """

    def __init__(
        self,
        code: str,
        *,
        retry: bool,
        detail: typing.Any = None,
        unreachable: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retry = retry
        self.detail = detail
        self.unreachable = unreachable


@dataclasses.dataclass
class Call:
    """One call of a step."""

    organization_id: str
    workflow_slug: str
    run_id: uuid.UUID
    node: wf.Node
    #: The rendered parameters.
    params: dict[str, typing.Any]
    state: dict[str, typing.Any]
    #: ``<run_id>:<node_key>``; the same for every attempt.
    idempotency_key: str
    #: The attempt of the step: 1, then one more for each retry.
    attempt: int = 1
    #: Seconds before the engine cancels this call, or ``None``.
    time_limit: float | None = None


@dataclasses.dataclass
class Outcome:
    output: dict[str, typing.Any] | None = None
    port: int = 0
    #: The step reports a failure (a deployment failed). Not retried.
    failed: bool = False
    #: Call the step again at this time, with ``state``.
    resume_at: datetime.datetime | None = None
    state: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Api:
    """imbi-api as the ``imbi-workflows`` service account."""

    def __init__(
        self, client: httpx.AsyncClient, config: settings.Workflows
    ) -> None:
        self._client = client
        self._config = config
        self._token: str | None = None
        self._expires_at = _now()
        self._lock = asyncio.Lock()

    async def bearer(self) -> str:
        async with self._lock:
            if self._token and _now() < self._expires_at:
                return self._token
            secret = self._config.sa_client_secret
            if not (self._config.sa_client_id and secret):
                raise StepError('service_account_not_configured', retry=False)
            response = await self._client.post(
                self._config.api_base_url + '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self._config.sa_client_id,
                    'client_secret': secret.get_secret_value(),
                },
            )
            if response.status_code != HTTP_OK:
                raise StepError(
                    f'token_http_{response.status_code}',
                    retry=response.status_code >= HTTP_SERVER_ERROR,
                )
            body = response.json()
            self._token = str(body['access_token'])
            # Refresh a minute early, so a call never starts with a token
            # about to lapse.
            self._expires_at = _now() + datetime.timedelta(
                seconds=int(body.get('expires_in', 900)) - 60
            )
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, typing.Any] | None = None,
        headers: dict[str, str] | None = None,
        wait_seconds: float | None = None,
    ) -> dict[str, typing.Any]:
        """Call imbi-api and return the JSON body.

        ``wait_seconds`` replaces the timeout of the client for this
        call.

        Raises:
            StepError: ``forbidden`` and other ``4xx`` responses are not
                retried; ``5xx`` responses and transport errors are. An
                error code in ``detail.error`` is retried when
                ``detail.retry`` is true.

        """
        try:
            response = await self._client.request(
                method,
                self._config.api_base_url + path,
                json=json,
                headers={
                    'Authorization': f'Bearer {await self.bearer()}',
                    **(headers or {}),
                },
                timeout=httpx.USE_CLIENT_DEFAULT
                if wait_seconds is None
                else wait_seconds,
            )
        except httpx.TransportError as e:
            raise StepError(
                type(e).__name__, retry=True, unreachable=True
            ) from e
        except httpx.HTTPError as e:
            raise StepError(type(e).__name__, retry=True) from e
        if response.status_code >= HTTP_CLIENT_ERROR:
            try:
                body: typing.Any = response.json()
            except ValueError:
                # For example, an HTML 502 page of a proxy.
                body = None
            detail: typing.Any = (
                typing.cast('dict[str, typing.Any]', body).get('detail')
                if isinstance(body, dict)
                else None
            )
            if response.status_code == HTTP_FORBIDDEN:
                raise StepError('forbidden', retry=False, detail=detail)
            if isinstance(detail, dict):
                found = typing.cast('dict[str, typing.Any]', detail)
                if found.get('error'):
                    raise StepError(
                        str(found['error']),
                        retry=found.get('retry') is True,
                        detail=detail,
                    )
            raise StepError(
                f'http_{response.status_code}',
                retry=response.status_code >= HTTP_SERVER_ERROR,
                detail=detail,
            )
        if not response.content:  # 204
            return {}
        return typing.cast('dict[str, typing.Any]', response.json())


_MODEL_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:SERVED_BY]->(p:AIProvider)
WHERE m.id = {ref} OR m.slug = {ref}
RETURN m.model_id AS model_id, m.enabled AS enabled,
       m.model_type AS model_type, p.driver AS driver,
       p.enabled AS provider_enabled, p.base_url AS base_url,
       p.credentials_encrypted AS credentials
"""

#: imbi-api records a release before its build; a failed build leaves
#: it with an open ``build-failure`` blocker and no tag on the remote.
_COMMIT_TAGS_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project}}})-[:HAS_RELEASE]->(r:Release)
WHERE COALESCE(r.tag, '') <> ''
  AND (r.committish = {committish} OR r.promoted_committish = {committish})
OPTIONAL MATCH (r)-[:BLOCKED_BY]->(b:Blocker)
WHERE b.status = 'open' AND b.type = 'build-failure'
RETURN r.tag AS tag, r.committish = {committish} AS exact,
       count(b) AS failed
"""

_FAILED_BUILD_TAGS_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project}}})-[:HAS_RELEASE]->(r:Release)
      -[:BLOCKED_BY]->(b:Blocker)
WHERE b.status = 'open' AND b.type = 'build-failure'
  AND COALESCE(r.tag, '') <> ''
RETURN DISTINCT r.tag AS tag
"""

_TAG_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project}}})-[:HAS_RELEASE]->(r:Release {{tag: {tag}}})
RETURN r.id AS id
"""

_ORG_SLUG_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org}}}) RETURN o.slug AS slug
"""

_DEPLOYMENTS_QUERY: typing.LiteralString = """
MATCH (d:Deployment)-[:BELONGS_TO]->(:Project {{id: {project}}}),
      (d)-[:TARGETS]->(:Environment {{slug: {env}}})
        -[:BELONGS_TO]->(:Organization {{id: {org}}}),
      (r:Release)-[:HAS_DEPLOYMENT]->(d)
RETURN r.tag AS tag, r.committish AS committish, d.status AS status,
       coalesce(d.updated_at, d.created_at) AS at
"""


async def _values(
    db: graph.Graph,
    query: typing.LiteralString,
    params: dict[str, typing.Any],
    columns: list[str],
) -> list[dict[str, typing.Any]]:
    records = await db.execute(query, params, columns)
    return [{c: graph.parse_agtype(r[c]) for c in columns} for r in records]


class Executors:
    def __init__(
        self,
        api: Api,
        db: graph.Graph,
        config: settings.Workflows,
        scripts: script_runner.Runner | None = None,
    ) -> None:
        self.api = api
        self.db = db
        self.config = config
        self.scripts = scripts

    async def run(self, call: Call) -> Outcome:  # noqa: PLR0911, PLR0912
        match call.node.type:
            case 'wait':
                return self._wait(call)
            case 'condition':
                return self._condition(call)
            case 'model_decision':
                return await self._model_decision(call)
            case 'script':
                return await self._script(call)
            case 'email':
                return await self._email(call)
            case 'slack':
                return await self._slack(call)
            case 'deploy':
                return await self._deploy(call)
            case 'rollback':
                return await self._rollback(call)
            case 'release':
                return await self._release(call)
            case 'agent':
                return await self._agent(call)
            case 'assign_ticket':
                return await self._assign_ticket(call)
            case 'llm_call':
                return await self._llm_call(call)
            case 'search_logs':
                return await self._search_logs(call)
            case other:
                step = registry.get(other)
                if step is not None and step.plugin:
                    return await self._plugin_step(call, step)
                raise StepError(f'unknown_type:{other}', retry=False)

    def _wait(self, call: Call) -> Outcome:
        params = _params(wait.Params, call)
        match = _DURATION.match(params.duration)
        if match is None:
            # The rendered value is itself a reference.
            raise StepError('invalid_params', retry=False)
        try:
            seconds = int(match.group(1)) * _UNITS[match.group(2)]
            resume_at = _now() + datetime.timedelta(seconds=seconds)
        except (OverflowError, ValueError) as e:
            raise StepError('invalid_params', retry=False) from e
        until = call.state.get('until')
        if until is None:
            return Outcome(
                resume_at=resume_at, state={'until': resume_at.isoformat()}
            )
        if _now() < datetime.datetime.fromisoformat(until):
            return Outcome(
                resume_at=datetime.datetime.fromisoformat(until),
                state=call.state,
            )
        return Outcome(output={'waited_seconds': seconds})

    def _condition(self, call: Call) -> Outcome:
        params = _params(condition.Params, call)
        try:
            output = condition.evaluate(params)
        except condition.EvaluationError as error:
            raise StepError(error.code, retry=False) from error
        return Outcome(
            output=output.model_dump(), port=0 if output.result else 1
        )

    async def _model_decision(self, call: Call) -> Outcome:
        params = _params(model_decision.Params, call)
        found = await _values(
            self.db,
            _MODEL_QUERY,
            {'ref': params.model_id},
            [
                'model_id',
                'enabled',
                'model_type',
                'driver',
                'provider_enabled',
                'base_url',
                'credentials',
            ],
        )
        model = found[0] if found else None
        if (
            model is None
            or model['enabled'] is False
            or model['provider_enabled'] is False
            or model['model_type'] != 'decision'
            or model['driver'] != 'typesafe'
        ):
            raise StepError('model_unavailable', retry=False)
        api_key = encryption.decrypt_config_value(model['credentials'])
        if not api_key:
            raise StepError('model_credentials_missing', retry=False)
        try:
            result = await typesafe.decide(
                api_key,
                drivers.resolve_base_url(model['driver'], model['base_url'])
                or '',
                str(model['model_id']),
                params.context or params.prompt,
                {
                    'decision': {
                        'type': 'choice',
                        'instructions': params.prompt,
                        'criteria': dict.fromkeys(params.branches),
                    }
                },
            )
        except typesafe.DecisionError as e:
            raise StepError(str(e), retry=True) from e
        answer: dict[str, typing.Any] = result['answers'].get('decision', {})
        choice = answer.get('choice')
        if choice not in params.branches:
            raise StepError('model_answer_invalid', retry=True)
        probability = float(answer.get('probabilities', {}).get(choice, 0))
        port = (
            params.branches.index(choice)
            if probability >= params.min_confidence
            else len(params.branches) - 1
        )
        return Outcome(
            output={
                'choice': choice,
                'probability': probability,
                'reasoning': answer.get('reasoning'),
            },
            port=port,
        )

    async def _script(self, call: Call) -> Outcome:
        params = _params(script.Params, call)
        if self.scripts is None:
            raise StepError('script_runner_unavailable', retry=False)
        try:
            done = await self.scripts.run(
                params, max_seconds=call.node.timeout_seconds
            )
        except script_runner.Busy as e:
            raise StepError('script_busy', retry=True) from e
        except script_runner.ScriptError as e:
            raise StepError(str(e), retry=e.retry) from e
        return Outcome(output=done.output, port=done.port)

    async def _email(self, call: Call) -> Outcome:
        _params(email.Params, call)
        org = await self.org_slug(call.organization_id)
        sent = await self.api.request(
            'POST',
            _path(
                'organizations',
                org,
                'workflows',
                call.workflow_slug,
                'runs',
                call.run_id,
                'steps',
                call.node.id,
                'email',
            ),
            headers={'Idempotency-Key': call.idempotency_key},
        )
        failed: list[str] = sent.get('failed') or []
        if failed:
            # Not retried: imbi-api stored this result with the key, and
            # the other recipients already have the message.
            raise StepError('email_failed: ' + ', '.join(failed), retry=False)
        return Outcome(output={'recipients': sent['recipients']})

    async def _slack(self, call: Call) -> Outcome:
        params = _params(slack.Params, call)
        if call.node.params.get('thread_ts') and params.thread_ts is None:
            # The reference has no value. A reply must not become a new
            # message in the channel.
            raise StepError('invalid_params', retry=False)
        org = await self.org_slug(call.organization_id)
        try:
            posted = await self.api.request(
                'POST',
                _path(
                    'organizations',
                    org,
                    'workflows',
                    call.workflow_slug,
                    'runs',
                    call.run_id,
                    'steps',
                    call.node.id,
                    'slack',
                ),
                headers={'Idempotency-Key': call.idempotency_key},
            )
        except StepError as e:
            if e.code == 'slack_ratelimited':
                # Nothing posted, and imbi-api released the key.
                raise StepError(e.code, retry=True) from e
            if e.code != 'slack_unreachable':
                raise
            # Slack may have posted: fail the step so that an operator
            # can mark it done or run it again.
            raise StepError('outcome_unknown', retry=False) from e
        if posted.get('error'):
            # Not retried: imbi-api stored this result with the key.
            raise StepError(f'slack_failed: {posted["error"]}', retry=False)
        return Outcome(
            output={
                'channel': posted['channel'],
                'ts': posted.get('ts'),
                'permalink': posted.get('permalink'),
            }
        )

    async def _assign_ticket(self, call: Call) -> Outcome:
        _params(assign_ticket.Params, call)
        org = await self.org_slug(call.organization_id)
        result = await self.api.request(
            'POST',
            _path(
                'organizations',
                org,
                'workflows',
                call.workflow_slug,
                'runs',
                call.run_id,
                'steps',
                call.node.id,
                'assign-ticket',
            ),
            # A replay returns the first result, so it cannot undo a
            # later hand-off.
            headers={'Idempotency-Key': call.idempotency_key},
        )
        return Outcome(output=result, port=0 if result['assignee'] else 1)

    async def _agent(self, call: Call) -> Outcome:
        params = _params(agent.Params, call)
        task = await self.api.request(
            'POST',
            await self._agent_task_path(
                call.organization_id,
                call.workflow_slug,
                call.run_id,
                call.node.id,
            ),
        )
        if task['outcome'] is None:
            return Outcome(
                resume_at=_now()
                + datetime.timedelta(seconds=self.config.agent_poll_seconds),
                state={'task_id': task['task_id']},
            )
        port = 0 if task['outcome'] in agent.SUCCEEDED else 1
        return Outcome(
            output={
                'task_id': task['task_id'],
                'outcome': task['outcome'],
                'reason': task['reason'],
                'summary': task['summary'],
                'result': _result(params, task.get('result'))
                if port == 0
                else None,
                # An imbi-api older than these fields leaves them out.
                **{
                    k: task.get(k) for k in agent.TicketAttributes.model_fields
                },
            },
            port=port,
            failed=port == 1,
            state={'task_id': task['task_id']},
        )

    async def _llm_call(self, call: Call) -> Outcome:
        params = _params(llm_call.Params, call)
        # Stop waiting before the engine cancels the call: a cancelled
        # call is a timeout, and its retry is a new attempt. The engine
        # limit includes the time to get the organization slug.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (call.time_limit or math.inf) * 0.9
        resume = Outcome(resume_at=_now(), state=call.state)
        try:
            async with asyncio.timeout_at(
                deadline if math.isfinite(deadline) else None
            ):
                org = await self.org_slug(call.organization_id)
        except TimeoutError:
            return resume
        except psycopg.OperationalError:
            # The graph is not reachable. An error here would make the
            # engine retry with a new key while an earlier call of this
            # attempt can still run, so ask again later with this key.
            LOGGER.warning(
                'LLM Call %s: organization lookup failed; asking again',
                call.node.id,
                exc_info=True,
            )
            return Outcome(
                resume_at=_now()
                + datetime.timedelta(seconds=LLM_CALL_POLL_SECONDS),
                state=call.state,
            )
        wait_seconds = min(LLM_CALL_TIMEOUT, deadline - loop.time())
        if wait_seconds <= 0:
            return resume
        # imbi-api still runs the call of this attempt, or the response
        # was lost and the outcome is unknown. Ask again with the same
        # key: a retry would be a new attempt and a second call.
        ask_again = Outcome(
            resume_at=_now()
            + datetime.timedelta(seconds=LLM_CALL_POLL_SECONDS),
            state=call.state,
        )
        try:
            # The httpx timeout applies to each phase of the request,
            # not to the total, so the total has its own limit.
            async with asyncio.timeout(wait_seconds):
                answer = await self.api.request(
                    'POST',
                    _path('organizations', org, 'prompts', 'run'),
                    json={
                        'ref': f'{params.prompt_ref}@{params.prompt_version}',
                        'variables': params.inputs,
                        'output_fields': [
                            f.model_dump(mode='json')
                            for f in params.output_fields
                        ],
                    },
                    headers={
                        'Idempotency-Key': (
                            f'{call.idempotency_key}:'
                            f'{call.state.get("key_attempt", call.attempt)}'
                        )
                    },
                    wait_seconds=wait_seconds,
                )
        except TimeoutError:
            return ask_again
        except StepError as e:
            # A 5xx with no error code, such as a failed record of the
            # answer, does not tell whether imbi-api made the call. A
            # failed token refresh while the call runs is the same.
            unknown = (
                e.retry and e.code.startswith(('http_', 'token_http_'))
            ) or isinstance(e.__cause__, httpx.HTTPError)
            if e.code != 'call_in_progress' and not unknown:
                raise
            return ask_again
        if answer.get('n') != params.prompt_version:
            raise StepError('prompt_version_mismatch', retry=False)
        return Outcome(
            output=llm_call.Output.model_validate(
                {**answer, 'prompt_version': answer['n']}
            ).model_dump(mode='json')
        )

    async def _plugin_step(
        self, call: Call, step: step_type.StepType
    ) -> Outcome:
        """Ask imbi-api to run one call of a plugin step (ADR 0032).

        Each call has its own key ``<run_id>:<node_id>:<attempt>:<poll>``.
        A step that acts and cannot tell whether it acted sends the key
        of the attempt that timed out again, so imbi-api gives the
        outcome of that call instead of a second call.
        """
        # By alias: imbi-api validates the plugin model by alias.
        params = _params(step.params, call).model_dump(
            mode='json', by_alias=True
        )
        integration = str(params.pop('integration'))
        project_id = params.pop('project_id', None)
        _check('integration', integration, _ID)
        _check('project_id', project_id, _ID)
        org = await self.org_slug(call.organization_id)
        attempt = (
            call.state.get('key_attempt', call.attempt)
            if step.side_effect and not step.idempotent
            else call.attempt
        )
        poll = int(call.state.get('poll', 0))
        key = f'{call.run_id}:{call.node.id}:{attempt}:{poll}'
        # imbi-api also limits each call to its own maximum.
        limit = call.time_limit * 0.9 if call.time_limit else None
        try:
            found = await self.api.request(
                'POST',
                _path(
                    'organizations',
                    org,
                    'integrations',
                    integration,
                    'workflow-steps',
                    step.type,
                    'run',
                ),
                json={
                    'params': params,
                    'project_id': project_id,
                    'call': base.StepCall(
                        run_id=str(call.run_id),
                        workflow_slug=call.workflow_slug,
                        node_id=call.node.id,
                        attempt=call.attempt,
                        idempotency_key=key,
                        state=call.state.get('poll_state', {}),
                    ).model_dump(mode='json'),
                    'time_limit_seconds': limit,
                },
                headers={'Idempotency-Key': key},
            )
        except StepError as e:
            if e.code != 'call_in_progress':
                raise
            # imbi-api still runs the call with this key: ask again.
            return Outcome(
                resume_at=_now()
                + datetime.timedelta(seconds=PLUGIN_CALL_POLL_SECONDS),
                state=call.state,
            )
        result = base.StepResult.model_validate(found)
        if result.poll:
            return Outcome(
                resume_at=_now()
                + datetime.timedelta(seconds=step.poll_seconds or 60),
                state={
                    **call.state,
                    'poll': poll + 1,
                    'poll_state': result.state,
                },
            )
        ports = step.ports or ('',)
        if result.port not in ports:
            raise StepError('plugin_result_invalid', retry=False)
        return Outcome(output=result.output, port=ports.index(result.port))

    async def _search_logs(self, call: Call) -> Outcome:
        params = _params(search_logs.Params, call)
        _check('project_id', params.project_id, _ID)
        query = {
            'source': params.source,
            'environment': params.environments,
            'start_time': params.start_time,
            'end_time': params.end_time,
            'cursor': params.cursor,
            'limit': params.limit,
            'filter': params.filters,
            'level': params.levels,
        }
        org = await self.org_slug(call.organization_id)
        found = await self.api.request(
            'GET',
            _path('organizations', org, 'projects', params.project_id, 'logs')
            + '/?'
            # An empty list sends nothing.
            + urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None},
                doseq=True,
            ),
        )
        base.LogResult.model_validate(found)
        return Outcome(output=found)

    async def cancel_agent_task(
        self,
        organization_id: str,
        slug: str,
        run_id: uuid.UUID,
        node_id: str,
    ) -> None:
        """Ask imbi-api to cancel the task of an agent step, if open."""
        await self.api.request(
            'POST',
            await self._agent_task_path(organization_id, slug, run_id, node_id)
            + '/cancel',
        )

    async def _agent_task_path(
        self,
        organization_id: str,
        slug: str,
        run_id: uuid.UUID,
        node_id: str,
    ) -> str:
        return _path(
            'organizations',
            await self.org_slug(organization_id),
            'workflows',
            slug,
            'runs',
            run_id,
            'steps',
            node_id,
            'agent-task',
        )

    async def notify_failure(
        self, organization_id: str, slug: str, run_id: uuid.UUID
    ) -> None:
        """Ask imbi-api to tell the owner team that a run failed."""
        org = await self.org_slug(organization_id)
        await self.api.request(
            'POST',
            _path(
                'organizations',
                org,
                'workflows',
                slug,
                'runs',
                run_id,
                'failure-notice',
            ),
            # A node key has no '/', so no step can make this key.
            headers={'Idempotency-Key': f'{run_id}/failure-notice'},
        )

    async def _deploy(self, call: Call) -> Outcome:
        params = _params(deploy.Params, call)
        return await self._deployment(
            call, params.project_id, params.environment, params.version
        )

    async def _rollback(self, call: Call) -> Outcome:
        params = _params(rollback.Params, call)
        _check('project_id', params.project_id, _ID)
        _check('environment', params.environment, _ID)
        version = call.state.get('version') or params.version
        if params.target != 'version' and 'run_id' not in call.state:
            version = await self._earlier_release(
                call.organization_id,
                params.project_id,
                params.environment,
                params.target,
            )
        return await self._deployment(
            call,
            params.project_id,
            params.environment,
            typing.cast('str', version),
            action='redeploy',
        )

    async def _earlier_release(
        self,
        organization_id: str,
        project_id: str,
        environment: str,
        target: str,
    ) -> str:
        """Return the release to roll back to.

        ``environment`` is a slug in the organization.
        ``last_healthy``: the newest release that succeeded, other than
        the release of the newest attempt. ``previous``: the release
        that succeeded before the one that serves now.
        """
        found = await _values(
            self.db,
            _DEPLOYMENTS_QUERY,
            {
                'project': project_id,
                'env': environment,
                'org': organization_id,
            },
            ['tag', 'committish', 'status', 'at'],
        )
        found.sort(key=lambda d: str(d['at']), reverse=True)
        releases = [str(d['tag'] or d['committish']) for d in found]
        succeeded = [
            str(d['tag'] or d['committish'])
            for d in found
            if d['status'] == 'success'
        ]
        if target == 'last_healthy':
            avoid = releases[0] if releases else None
        else:
            avoid = succeeded[0] if succeeded else None
        for candidate in succeeded:
            if candidate != avoid:
                return candidate
        raise StepError('no_release_to_roll_back_to', retry=False)

    async def _deployment(
        self,
        call: Call,
        project_id: str,
        environment: str,
        version: str,
        action: str = 'deploy',
    ) -> Outcome:
        _check('project_id', project_id, _ID)
        _check('environment', environment, _ID)
        _check('version', version, _REF)
        base = await self._deployments_path(call.organization_id, project_id)
        run_id = call.state.get('run_id')
        if run_id is None:
            commit = await self.api.request(
                'GET', base + _path('commits', version)
            )
            started = await self.api.request(
                'POST',
                base,
                json={
                    'action': action,
                    'environment': environment,
                    'committish': commit['sha'],
                    'ref_label': version,
                },
                headers={'Idempotency-Key': call.idempotency_key},
            )
            run: dict[str, typing.Any] = started['run']
        else:
            run = await self.api.request('GET', base + _path('runs', run_id))
        return self._run_outcome(run, {'version': version})

    def _run_outcome(
        self, run: dict[str, typing.Any], state: dict[str, typing.Any]
    ) -> Outcome:
        state = {**state, 'run_id': str(run['run_id'])}
        port = _DEPLOYMENT_PORTS.get(str(run.get('status')))
        if port is None:
            return Outcome(resume_at=self._poll_at(), state=state)
        return Outcome(
            output={
                'deployment_id': str(run['run_id']),
                'status': str(run['status']),
            },
            port=port,
            failed=port == 1,
        )

    async def _release(self, call: Call) -> Outcome:
        params = _params(release.Params, call)
        _check('project_id', params.project_id, _ID)
        _check('environment', params.environment, _ID)
        _check('from_environment', params.from_environment, _ID)
        _check('commit', params.commit, _REF)
        _check('tag', params.tag or None, _REF)
        base = await self._deployments_path(
            call.organization_id, params.project_id
        )
        if 'tag' not in call.state:
            try:
                chosen = await self._choose(call, params, base)
            except _Refused as e:
                return _refused(e.reason)
            # Kept before the promote: a retry sends the same release.
            return Outcome(resume_at=_now(), state=chosen)
        state = {k: call.state[k] for k in ('tag', 'notes', 'degraded', 'sha')}
        if 'artifact_run_id' in call.state:
            return await self._promote_status(
                call, params, state, str(call.state['artifact_run_id'])
            )
        run_id = call.state.get('run_id')
        if run_id is None:
            return await self._promote(call, params, base, state)
        run = await self.api.request('GET', base + _path('runs', run_id))
        return _with_tag(self._run_outcome(run, state), state)

    async def _promote(
        self,
        call: Call,
        params: release.Params,
        base: str,
        state: dict[str, typing.Any],
    ) -> Outcome:
        try:
            started = await self._refusable(
                'POST',
                base,
                json={
                    'action': 'promote',
                    'from_environment': params.from_environment,
                    'to_environment': params.environment,
                    'from_committish': state['sha'],
                    'tag': state['tag'],
                    'release_notes_markdown': state['notes'],
                },
                headers={'Idempotency-Key': call.idempotency_key},
            )
        except _Refused as e:
            return _tagged(state, '', 'refused', e.reason)
        if started.get('phase') != 'building':
            run: dict[str, typing.Any] = started['run']
            if started.get('recorded') is False or not run.get('run_id'):
                # imbi-api answers 202 when the deployment did not start,
                # and says why in warning.
                return _tagged(
                    state,
                    '',
                    str(run.get('status')),
                    started.get('warning') or 'deployment_not_reported',
                )
            return _with_tag(self._run_outcome(run, state), state)
        # A Release workflow builds first; promote-status reports the rest.
        artifact = str(started.get('artifact_run_id') or '')
        if started.get('watched') is False:
            # Nothing would move promote-status past building.
            return _tagged(state, artifact, 'building', 'promote_not_watched')
        return Outcome(
            resume_at=self._poll_at(),
            state={**state, 'artifact_run_id': artifact},
        )

    async def _promote_status(
        self,
        call: Call,
        params: release.Params,
        state: dict[str, typing.Any],
        artifact: str,
    ) -> Outcome:
        base = await self._deployments_path(
            call.organization_id, params.project_id
        )
        found = await self.api.request('GET', base + _path('promote-status'))
        ours = (
            found.get('artifact_run_id') == artifact
            if artifact
            else (found.get('tag'), found.get('environment'))
            == (state['tag'], params.environment)
        )
        if not ours:
            # One record per project, rewritten by each promote in flight.
            return await self._tag_deployment(call, params, state, artifact)
        status = str(found.get('status'))
        if status in ('building', 'deploying'):
            return Outcome(
                resume_at=self._poll_at(),
                state={**state, 'artifact_run_id': artifact},
            )
        if status == 'success':
            return _tagged(state, artifact, status)
        error = found.get('error')
        return _tagged(
            state, artifact, status, f'{status}: {error}' if error else status
        )

    async def _tag_deployment(
        self,
        call: Call,
        params: release.Params,
        state: dict[str, typing.Any],
        artifact: str,
    ) -> Outcome:
        # The step cut the tag, so every deployment of it is this one.
        deployed = [
            d
            for d in await self._deployments(call, params)
            if d['tag'] == state['tag']
        ]
        status = str(deployed[0]['status']) if deployed else ''
        port = _DEPLOYMENT_NODE_PORTS.get(status)
        if port is not None:
            return _tagged(
                state,
                artifact,
                status,
                f'deployment_{status}' if port else None,
            )
        if state['tag'] in await self._failed_build_tags(params):
            return _tagged(state, artifact, 'build_failed', 'build_failed')
        return Outcome(
            resume_at=self._poll_at(),
            state={**state, 'artifact_run_id': artifact},
        )

    def _poll_at(self) -> datetime.datetime:
        return _now() + datetime.timedelta(
            seconds=self.config.deploy_poll_seconds
        )

    async def _choose(
        self, call: Call, params: release.Params, base: str
    ) -> dict[str, typing.Any]:
        commit = await self._refusable(
            'GET', base + _path('commits', params.commit)
        )
        sha = str(commit['sha'])
        existing = await self._commit_tag(params.project_id, sha)
        if existing:
            # A deploy step deploys an existing tag.
            raise _Refused(f'commit_already_tagged: {existing}')
        tag, notes = params.tag, params.release_notes
        draft: dict[str, typing.Any] = {}
        if not (tag and notes):
            draft = await self._draft(call, params, base, sha)
        tag = tag or str(draft['version'])
        _check('tag', tag, _REF)
        if await _values(
            self.db,
            _TAG_QUERY,
            {'project': params.project_id, 'tag': tag},
            ['id'],
        ):
            # Cutting it again would ship the code of the existing tag.
            raise _Refused(f'tag_exists: {tag}')
        return {
            'tag': tag,
            'notes': notes or str(draft.get('notes_markdown') or ''),
            'degraded': draft.get('degraded') is True,
            'sha': sha,
        }

    async def _draft(
        self, call: Call, params: release.Params, base: str, sha: str
    ) -> dict[str, typing.Any]:
        drift = await self._refusable('GET', base + _path('release-drift'))
        running = [
            d
            for d in await self._deployments(call, params)
            if d['status'] == 'success'
        ]
        # As the promote card: from the newest tag, or the deployed one, or
        # the history when there is none; the version also bumps past failed
        # builds, whose tags are taken but never reached the remote.
        bump_from = drift.get('latest_tag') or (
            running[0]['tag'] if running else None
        )
        return await self._refusable(
            'POST',
            base + _path('draft-release-notes'),
            json={
                'base_sha': bump_from or '',
                'head_sha': sha,
                'last_tag': _newest(
                    bump_from, *await self._failed_build_tags(params)
                ),
            },
        )

    async def _deployments(
        self, call: Call, params: release.Params
    ) -> list[dict[str, typing.Any]]:
        found = await _values(
            self.db,
            _DEPLOYMENTS_QUERY,
            {
                'project': params.project_id,
                'env': params.environment,
                'org': call.organization_id,
            },
            ['tag', 'committish', 'status', 'at'],
        )
        return sorted(found, key=lambda d: str(d['at']), reverse=True)

    async def _failed_build_tags(self, params: release.Params) -> list[str]:
        found = await _values(
            self.db,
            _FAILED_BUILD_TAGS_QUERY,
            {'project': params.project_id},
            ['tag'],
        )
        return [str(f['tag']) for f in found]

    async def _commit_tag(self, project_id: str, sha: str) -> str | None:
        found = await _values(
            self.db,
            _COMMIT_TAGS_QUERY,
            {
                'project': project_id,
                'committish': versioning.short_committish(sha),
            },
            ['tag', 'exact', 'failed'],
        )
        found = [f for f in found if not f['failed']]
        exact = {str(f['tag']) for f in found if f['exact'] is True}
        tags = sorted(exact or {str(f['tag']) for f in found})
        if len(tags) > 1:
            raise _Refused(f'commit_has_several_tags: {", ".join(tags)}')
        return tags[0] if tags else None

    async def _refusable(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, typing.Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, typing.Any]:
        try:
            return await self.api.request(
                method, path, json=json, headers=headers
            )
        except StepError as e:
            reason = _refusal(e)
            if reason is None:
                raise
            raise _Refused(reason) from e

    async def _deployments_path(
        self, organization_id: str, project_id: str
    ) -> str:
        org = await self.org_slug(organization_id)
        return _path(
            'organizations', org, 'projects', project_id, 'deployments'
        )

    async def org_slug(self, organization_id: str) -> str:
        found = await _values(
            self.db, _ORG_SLUG_QUERY, {'org': organization_id}, ['slug']
        )
        if not found:
            raise StepError('organization_not_found', retry=False)
        return str(found[0]['slug'])


def _tagged(
    state: dict[str, typing.Any],
    deployment_id: str,
    status: str,
    error: str | None = None,
) -> Outcome:
    return Outcome(
        output=release.Output(
            deployment_id=deployment_id,
            status=status,
            tag=state['tag'],
            release_notes=state['notes'],
            degraded=state['degraded'],
            error=error,
        ).model_dump(mode='json'),
        port=0 if error is None else 1,
        failed=error is not None,
    )


def _with_tag(outcome: Outcome, state: dict[str, typing.Any]) -> Outcome:
    if outcome.output is None:
        return outcome
    status = str(outcome.output['status'])
    return _tagged(
        state,
        str(outcome.output['deployment_id']),
        status,
        f'deployment_{status}' if outcome.failed else None,
    )


def _newest(*tags: typing.Any) -> str | None:
    named = [str(t) for t in tags if t]
    ranked = [
        (key, t)
        for t in named
        if (key := versioning.release_version_key(t)) is not None
    ]
    if ranked:
        return max(ranked)[1]
    return named[0] if named else None


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_REFUSALS = frozenset({'http_400', 'http_404', 'http_409'})


def _refusal(error: StepError) -> str | None:
    """Return why imbi-api refused a promote, or ``None``.

    imbi-api gives the reason as text (an open blocker, a failing CI, an
    environment it cannot promote to), or as the code of a ``403``. A
    detail with an error code, such as ``outcome_unknown``, is not one.
    """
    detail = error.detail
    if error.code in _REFUSALS and isinstance(detail, str):
        return detail
    if error.code == 'forbidden' and isinstance(detail, dict):
        found = typing.cast('dict[str, typing.Any]', detail)
        if found.get('error'):
            message = found.get('message')
            code = str(found['error'])
            return f'{code}: {message}' if message else code
    return None


def _refused(error: str) -> Outcome:
    return _tagged(
        {'tag': None, 'notes': '', 'degraded': False}, '', 'refused', error
    )


def _check(name: str, value: str | None, pattern: re.Pattern[str]) -> None:
    """Refuse a value that is not safe in a URL or a ref. Not retried."""
    if value is not None and not pattern.match(value):
        raise StepError(f'invalid_{name}', retry=False)


def _path(*segments: object) -> str:
    """Return ``/a/b/c`` with every segment quoted."""
    return ''.join('/' + urllib.parse.quote(str(s), safe='') for s in segments)


def _result(
    params: agent.Params, result: dict[str, typing.Any] | None
) -> dict[str, typing.Any] | None:
    """Return the structured output with every field of the step."""
    if result is None:
        return None
    return agent.complete_result(params.output_fields, result)


def _params[T: pydantic.BaseModel](model: type[T], call: Call) -> T:
    try:
        return model.model_validate(call.params)
    except pydantic.ValidationError as e:
        raise StepError('invalid_params', retry=False) from e
