"""Step executors (ADR 0021).

Each executor runs one call of one step and returns an
:class:`Outcome`. A step that spans claims (a wait, a deployment that
rolls out) returns ``resume_at`` and its progress in ``state``; the
engine calls it again with that state when the run is due.

Deploy, rollback, and email go through imbi-api as the
``imbi-workflows`` service account, so the bounds of ADR 0017 apply to
deployments, and imbi-api sends email only to users and teams of the
organization. They send the idempotency key ``<run_id>:<node_key>``:
after a crash the engine calls them again, and imbi-api returns the
first result instead of acting again, or ``409 outcome_unknown``.
"""

import asyncio
import dataclasses
import datetime
import logging
import re
import typing
import urllib.parse
import uuid

import httpx
import pydantic

from imbi.common import graph
from imbi.common.auth import encryption
from imbi.common.llm import drivers, typesafe
from imbi.common.workflows import graph as wf
from imbi.common.workflows.registry import (
    deploy,
    email,
    model_decision,
    rollback,
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

_DURATION = re.compile(r'^([1-9][0-9]*)([smhd])$')
_UNITS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}

#: Statuses of a deployment run that end it, and the port they take.
_DEPLOYMENT_PORTS = {'success': 0, 'failure': 1, 'cancelled': 1}

HTTP_OK = 200
HTTP_CLIENT_ERROR = 400
HTTP_FORBIDDEN = 403
HTTP_SERVER_ERROR = 500


class StepError(Exception):
    """A step call failed. ``code`` is stored as the step's error."""

    def __init__(self, code: str, *, retry: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retry = retry


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
    ) -> dict[str, typing.Any]:
        """Call imbi-api and return the JSON body.

        Raises:
            StepError: ``forbidden`` and other ``4xx`` responses are not
                retried; ``5xx`` responses and transport errors are.

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
            )
        except httpx.HTTPError as e:
            raise StepError(type(e).__name__, retry=True) from e
        if response.status_code == HTTP_FORBIDDEN:
            raise StepError('forbidden', retry=False)
        if response.status_code >= HTTP_CLIENT_ERROR:
            detail: typing.Any = response.json().get('detail')
            if isinstance(detail, dict):
                error = typing.cast('dict[str, typing.Any]', detail).get(
                    'error'
                )
                if error:
                    raise StepError(str(error), retry=False)
            raise StepError(
                f'http_{response.status_code}',
                retry=response.status_code >= HTTP_SERVER_ERROR,
            )
        return typing.cast('dict[str, typing.Any]', response.json())


_MODEL_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:SERVED_BY]->(p:AIProvider)
WHERE m.id = {ref} OR m.slug = {ref}
RETURN m.model_id AS model_id, m.enabled AS enabled,
       m.model_type AS model_type, p.driver AS driver,
       p.enabled AS provider_enabled, p.base_url AS base_url,
       p.credentials_encrypted AS credentials
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
        self, api: Api, db: graph.Graph, config: settings.Workflows
    ) -> None:
        self.api = api
        self.db = db
        self.config = config

    async def run(self, call: Call) -> Outcome:
        match call.node.type:
            case 'wait':
                return self._wait(call)
            case 'model_decision':
                return await self._model_decision(call)
            case 'email':
                return await self._email(call)
            case 'deploy':
                return await self._deploy(call)
            case 'rollback':
                return await self._rollback(call)
            case other:
                raise StepError(f'unknown_type:{other}', retry=False)

    def _wait(self, call: Call) -> Outcome:
        params = _params(wait.Params, call)
        match = _DURATION.match(params.duration)
        seconds = int(match.group(1)) * _UNITS[match.group(2)] if match else 0
        until = call.state.get('until')
        if until is None:
            resume_at = _now() + datetime.timedelta(seconds=seconds)
            return Outcome(
                resume_at=resume_at, state={'until': resume_at.isoformat()}
            )
        if _now() < datetime.datetime.fromisoformat(until):
            return Outcome(
                resume_at=datetime.datetime.fromisoformat(until),
                state=call.state,
            )
        return Outcome(output={'waited_seconds': seconds})

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

        ponytail: reads ``Deployment`` nodes only, not the legacy
        ``DEPLOYED_TO`` arrays; history from before that migration is
        not seen.
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
        for release in succeeded:
            if release != avoid:
                return release
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
        state = {'run_id': str(run['run_id']), 'version': version}
        port = _DEPLOYMENT_PORTS.get(str(run.get('status')))
        if port is None:
            return Outcome(
                resume_at=_now()
                + datetime.timedelta(seconds=self.config.deploy_poll_seconds),
                state=state,
            )
        return Outcome(
            output={
                'deployment_id': str(run['run_id']),
                'status': str(run['status']),
            },
            port=port,
            failed=port == 1,
        )

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


def _check(name: str, value: str | None, pattern: re.Pattern[str]) -> None:
    """Refuse a value that is not safe in a URL or a ref. Not retried."""
    if value is not None and not pattern.match(value):
        raise StepError(f'invalid_{name}', retry=False)


def _path(*segments: object) -> str:
    """Return ``/a/b/c`` with every segment quoted."""
    return ''.join('/' + urllib.parse.quote(str(s), safe='') for s in segments)


def _params[T: pydantic.BaseModel](model: type[T], call: Call) -> T:
    try:
        return model.model_validate(call.params)
    except pydantic.ValidationError as e:
        raise StepError('invalid_params', retry=False) from e
