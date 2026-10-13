"""The resolution service of the secrets broker (ADR 0022, plan 9.4/9.5).

These are functions for trusted callers, not routes. The caller gives a
:class:`ResolutionContext` that it took from the agent token and the
chain pin (organization, agent, project, task, runner); a request can
never set them. The harness routes that call this service come with the
runner tokens (plan phase P2).

Rules that this module keeps:

- Access is denied unless exactly one enabled grant allows the whole
  request. Missing context is a denial.
- A handle has 256 random bits and is stored only as an HMAC, with a key
  derived from ``IMBI_AUTH_JWT_SECRET`` and a label of its own.
- Materialization checks the provider, binding, and grant again, and
  consumes the handle and the nonce in one transaction, so one handle
  gives material at most ``materialization_limit`` times.
- Release and provider revocation are separate results. A failed
  revocation stays ``failed`` and the sweep tries it again.
- Material is held only in :class:`~.providers.Material` and
  :class:`Materialization`; neither has a readable ``repr``.
"""

import base64
import dataclasses
import datetime
import hashlib
import hmac
import logging
import re
import secrets
import typing
import uuid

import psycopg
import psycopg.errors
import psycopg_pool
from psycopg import rows

from imbi.api.secret_broker import audit, providers
from imbi.common import settings
from imbi.common.auth import encryption

LOGGER = logging.getLogger(__name__)

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Conn = psycopg.AsyncConnection[typing.Any]
type Row = dict[str, typing.Any]

DeliveryMode = typing.Literal[
    'file_descriptor', 'stdin', 'file', 'environment'
]
DELIVERY_MODES: tuple[DeliveryMode, ...] = typing.get_args(DeliveryMode)

#: The upper limit of any resolution lifetime, in seconds.
MAX_TTL_SECONDS = 3600

#: Response headers of a materialization (plan 9.1, rule 13). The route
#: also turns off body capture.
NO_STORE_HEADERS: dict[str, str] = {
    'Cache-Control': 'no-store',
    'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
}

_HANDLE_LABEL = b'imbi-secret-handle-v1'
_NONCE_LABEL = b'imbi-secret-nonce-v1'
_HANDLE_PREFIX = 'imh_'

_REFERENCE = re.compile(
    r'secret://(?P<scope>[a-z0-9_]+)/(?P<path>[a-z0-9_]+(?:/[a-z0-9_]+)*)'
    r'(?:#(?P<field>[A-Za-z0-9_-]+))?'
)
_MAX_REFERENCE_LENGTH = 512
PURPOSE = re.compile(r'[a-z][a-z0-9_]{0,63}')
_ENV_NAME = re.compile(r'[A-Z][A-Z0-9_]{0,127}')
_FILE_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')
#: Environment names that change how a process loads, runs, trusts TLS,
#: or routes its traffic. A name is refused when it is in this set,
#: starts with a prefix, or ends with a suffix below.
_UNSAFE_ENV = frozenset(
    {
        'BASH_ENV',
        'CURL_CA_BUNDLE',
        'ENV',
        'HOME',
        'IFS',
        'PATH',
        'PERL5OPT',
        'PROMPT_COMMAND',
        'PS4',
        'REQUESTS_CA_BUNDLE',
        'RUBYOPT',
        'SHELL',
        'SHELLOPTS',
    }
)
_UNSAFE_ENV_PREFIXES = (
    'BASH_FUNC_',
    'DYLD_',
    'GCONV_',
    'GIT_',
    'JAVA_',
    'JDK_',
    'LD_',
    'NODE_',
    'PYTHON',
    'SSL_CERT_',
)
_UNSAFE_ENV_SUFFIXES = ('_PROXY',)


# --- References and request syntax ---------------------------------------


@dataclasses.dataclass(frozen=True)
class Reference:
    """A parsed ``secret://<scope>/<path>[#<field>]``."""

    scope: str
    path: str
    field: str | None

    @property
    def binding(self) -> str:
        """The reference without the field: what a binding stores."""
        return f'secret://{self.scope}/{self.path}'

    def __str__(self) -> str:
        return self.binding + (f'#{self.field}' if self.field else '')


def parse_reference(value: str, *, field: bool = True) -> Reference:
    """Parse a reference. Only the canonical form is accepted.

    Scope and path segments are lower case letters, digits, and
    underscores. Matching is case sensitive. There is no other
    spelling of a reference, so the input is its canonical form.

    Raises:
        BrokerError: ``invalid_secret_reference``.

    """
    match = (
        _REFERENCE.fullmatch(value)
        if len(value) <= _MAX_REFERENCE_LENGTH
        else None
    )
    if match is None or (not field and match['field']):
        raise providers.BrokerError('invalid_secret_reference')
    return Reference(match['scope'], match['path'], match['field'])


def check_delivery(mode: str, target: str | None) -> str | None:
    """Return the delivery target when it is safe for its mode.

    - ``environment``: an upper case name that does not change how a
      process loads or runs (``PATH``, ``LD_*``, ...)
    - ``file``: a plain file name; the executor puts it in a private
      directory
    - ``file_descriptor``: a descriptor number from 3 to 255
    - ``stdin``: no target

    Raises:
        BrokerError: ``delivery_mode_not_allowed``.

    """
    ok = False
    if mode == 'environment':
        ok = (
            target is not None
            and _ENV_NAME.fullmatch(target) is not None
            and target not in _UNSAFE_ENV
            and not target.startswith(_UNSAFE_ENV_PREFIXES)
            and not target.endswith(_UNSAFE_ENV_SUFFIXES)
        )
    elif mode == 'file':
        ok = target is not None and _FILE_NAME.fullmatch(target) is not None
    elif mode == 'file_descriptor':
        ok = target is not None and target.isascii() and target.isdigit()
        ok = ok and 3 <= int(typing.cast(str, target)) <= 255
    elif mode == 'stdin':
        ok = not target
        target = None
    if not ok:
        raise providers.BrokerError(
            'delivery_mode_not_allowed', 'invalid_target'
        )
    return target


def _digest(label: bytes, value: str) -> bytes:
    """Return the keyed hash of a handle or a nonce.

    The key is derived from ``IMBI_AUTH_JWT_SECRET`` with a label of its
    own, as other service secrets are, so it changes when that secret
    rotates (every open handle then stops working).
    """
    key = hmac.new(
        settings.get_auth_settings().jwt_secret.encode(),
        label,
        hashlib.sha256,
    ).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


# --- Service types --------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ResolutionContext:
    """Who asks, from trusted state only (the token and the chain pin)."""

    organization_id: str
    agent_id: str
    project_id: str | None
    task_id: uuid.UUID
    runner_id: str


@dataclasses.dataclass(frozen=True)
class ResolutionRequest:
    """What the runner asks for."""

    reference: str
    purpose: str
    ttl_seconds: int
    delivery_mode: str
    delivery_target: str | None = None
    idempotency_key: str | None = None


@dataclasses.dataclass(frozen=True)
class Created:
    """A new resolution. ``handle`` goes to the executor only."""

    resolution_id: uuid.UUID
    handle: str = dataclasses.field(repr=False)
    state: str
    expires_at: datetime.datetime
    delivery_mode: str
    delivery_target: str | None


@dataclasses.dataclass(frozen=True)
class ExecutorContext:
    """The runner that the executor credential belongs to."""

    runner_id: str


@dataclasses.dataclass(frozen=True)
class MaterializeRequest:
    """What the executor sends. The context must equal the resolution."""

    handle: str = dataclasses.field(repr=False)
    nonce: str = dataclasses.field(repr=False)
    task_id: uuid.UUID
    agent_id: str
    project_id: str | None
    purpose: str


class Materialization:
    """Material for one child process. No readable ``repr``, no pickle."""

    __slots__ = (
        'credential_expires_at',
        'delivery_mode',
        'delivery_target',
        'encoding',
        'material',
        'resolution_expires_at',
        'resolution_id',
    )

    def __init__(
        self,
        row: Row,
        material: providers.Material,
    ) -> None:
        self.resolution_id: uuid.UUID = row['id']
        self.delivery_mode: str = row['delivery_mode']
        self.delivery_target: str | None = row['delivery_target']
        self.resolution_expires_at: datetime.datetime = row['expires_at']
        self.credential_expires_at = material.credential_expires_at
        self.encoding, self.material = _encode(material)

    def __repr__(self) -> str:
        return f'<Materialization {self.resolution_id} redacted>'

    __str__ = __repr__

    def __reduce__(self) -> typing.NoReturn:
        raise TypeError('Materialization cannot be serialized')

    def body(self) -> dict[str, typing.Any]:
        """The response body. Send it with :data:`NO_STORE_HEADERS`."""
        return {
            'resolution_id': str(self.resolution_id),
            'encoding': self.encoding,
            'material': self.material,
            'delivery': {
                'mode': self.delivery_mode,
                'target': self.delivery_target,
            },
            'resolution_expires_at': self.resolution_expires_at.isoformat(),
            'credential_expires_at': (
                self.credential_expires_at.isoformat()
                if self.credential_expires_at
                else None
            ),
        }


def _encode(material: providers.Material) -> tuple[str, str]:
    if not material.binary:
        try:
            return 'utf8', material.value.decode('utf-8')
        except UnicodeDecodeError:
            pass
    return 'base64', base64.b64encode(material.value).decode('ascii')


@dataclasses.dataclass(frozen=True)
class Decision:
    """The binding, provider, and the one grant that allow a request."""

    binding: Row
    provider: Row
    grant: Row


# --- Policy ---------------------------------------------------------------

#: The enabled grants of an organization that allow a binding for an
#: agent, a project, a purpose, and a delivery mode. A grant with no
#: project ids allows any project; a task with no project matches only
#: such a grant.
_GRANT_MATCH = (
    'SELECT * FROM secrets.grants'
    ' WHERE organization_id = %(org)s AND enabled'
    ' AND %(binding)s = ANY(binding_ids)'
    ' AND %(agent)s = ANY(agent_ids)'
    ' AND %(purpose)s = ANY(purposes)'
    ' AND %(mode)s = ANY(delivery_modes)'
    ' AND (cardinality(project_ids) = 0'
    '      OR %(project)s::TEXT = ANY(project_ids))'
)


def required_capability(credential_class: str) -> providers.Capability:
    return (
        'dynamic_issuance'
        if credential_class == 'dynamic'
        else 'static_retrieval'
    )


async def _fetch(
    conn: Conn, query: typing.LiteralString, params: typing.Any
) -> list[Row]:
    async with conn.cursor(row_factory=rows.dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def _fetch_one(
    conn: Conn, query: typing.LiteralString, params: typing.Any
) -> Row | None:
    found = await _fetch(conn, query, params)
    return found[0] if found else None


def _check_binding(binding: Row | None, reference: Reference) -> Row:
    if binding is None:
        raise providers.BrokerError('secret_binding_not_found')
    if not binding['enabled']:
        raise providers.BrokerError('secret_binding_disabled')
    # A binding with a field list gives only those fields; a binding
    # without one gives the whole value only.
    allowed: list[str] = binding['allowed_fields']
    if (reference.field is None and allowed) or (
        reference.field is not None and reference.field not in allowed
    ):
        raise providers.BrokerError('secret_field_not_allowed')
    return binding


def _check_provider(provider: Row | None, binding: Row) -> Row:
    if provider is None or not provider['enabled']:
        raise providers.BrokerError('secret_provider_disabled')
    plugin = providers.get(provider['type'])
    needed = required_capability(binding['credential_class'])
    if needed not in plugin.capabilities:
        raise providers.BrokerError(
            'operation_not_supported', f'missing_{needed}'
        )
    return provider


async def evaluate(
    conn: Conn,
    organization_id: str,
    agent_id: str,
    project_id: str | None,
    reference: Reference,
    purpose: str,
    delivery_mode: str,
    ttl_seconds: int,
) -> Decision:
    """Return the decision for a request, or raise the denial.

    No provider call. The binding row is locked ``FOR SHARE`` until the
    transaction ends, so it cannot be deleted under a new resolution.

    Raises:
        BrokerError: The request is denied.

    """
    if not PURPOSE.fullmatch(purpose):
        raise providers.BrokerError('secret_access_denied', 'invalid_purpose')
    if delivery_mode not in DELIVERY_MODES:
        raise providers.BrokerError('delivery_mode_not_allowed')
    if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
        raise providers.BrokerError('requested_ttl_too_large')
    binding = _check_binding(
        await _fetch_one(
            conn,
            'SELECT * FROM secrets.bindings'
            ' WHERE organization_id = %s AND reference = %s FOR SHARE',
            (organization_id, reference.binding),
        ),
        reference,
    )
    provider = _check_provider(
        await _fetch_one(
            conn,
            'SELECT * FROM secrets.providers WHERE id = %s',
            (binding['provider_id'],),
        ),
        binding,
    )
    if delivery_mode not in binding['allowed_delivery_modes']:
        raise providers.BrokerError('delivery_mode_not_allowed')
    if ttl_seconds > binding['max_ttl_seconds']:
        raise providers.BrokerError('requested_ttl_too_large')
    grants = await _fetch(
        conn,
        _GRANT_MATCH,
        {
            'org': organization_id,
            'binding': binding['id'],
            'agent': agent_id,
            'purpose': purpose,
            'mode': delivery_mode,
            'project': project_id,
        },
    )
    if not grants:
        raise providers.BrokerError('secret_access_denied', 'no_grant')
    if len(grants) > 1:
        raise providers.BrokerError('secret_access_denied', 'ambiguous_grants')
    if ttl_seconds > grants[0]['max_ttl_seconds']:
        raise providers.BrokerError('requested_ttl_too_large')
    return Decision(binding, provider, grants[0])


async def _check_task(conn: Conn, context: ResolutionContext) -> None:
    """The task must be open and match the trusted context."""
    task = await _fetch_one(
        conn,
        'SELECT organization_id, agent_id, project_id, status'
        ' FROM agent_runtime.tasks WHERE id = %s',
        (context.task_id,),
    )
    if task is None or (
        task['organization_id'],
        task['agent_id'],
        task['project_id'],
    ) != (context.organization_id, context.agent_id, context.project_id):
        raise providers.BrokerError(
            'resolution_context_mismatch', 'task_mismatch'
        )
    if task['status'] == 'closed':
        raise providers.BrokerError('secret_access_denied', 'task_closed')


def _event(
    event_type: audit.EventType,
    row: Row,
    *,
    result: audit.Result = 'succeeded',
    reason: str = '',
    actor: str = '',
) -> audit.Event:
    """Return an audit event with the ids of a resolution row."""

    def text(key: str) -> str:
        value = row.get(key)
        return '' if value is None else str(value)

    return audit.Event(
        organization_id=row['organization_id'],
        type=event_type,
        result=result,
        reason=reason,
        actor=actor or f'runner:{text("runner_id")}',
        agent_id=text('agent_id'),
        project_id=text('project_id'),
        task_id=text('task_id'),
        runner_id=text('runner_id'),
        provider_id=text('provider_id'),
        binding_id=text('binding_id'),
        grant_id=text('grant_id'),
        resolution_id=text('id'),
        purpose=text('purpose'),
        delivery_mode=text('delivery_mode'),
    )


def _new_handle() -> str:
    return _HANDLE_PREFIX + secrets.token_urlsafe(32)


# --- The service ----------------------------------------------------------


class Broker:
    """Create, materialize, release, and expire resolutions."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def create_resolution(
        self, context: ResolutionContext, request: ResolutionRequest
    ) -> Created:
        """Create a resolution and return its handle.

        A repeat with the same ``idempotency_key`` for the task gives
        the first resolution a new handle, while nothing has used it.
        The old handle stops working.

        Raises:
            BrokerError: The request is denied.

        """
        context_row: Row = {
            'organization_id': context.organization_id,
            'agent_id': context.agent_id,
            'project_id': context.project_id,
            'task_id': context.task_id,
            'runner_id': context.runner_id,
            'purpose': request.purpose,
            'delivery_mode': request.delivery_mode,
        }
        try:
            for attempt in (1, 2):
                try:
                    created, row = await self._create(context, request)
                    break
                except psycopg.errors.UniqueViolation as err:
                    # A concurrent create with the same key won the race:
                    # the second attempt takes the repeat path.
                    if (
                        err.diag.constraint_name
                        != 'resolutions_task_idempotency_key'
                        or attempt == 2
                    ):
                        raise
            else:  # pragma: no cover - the loop breaks or raises
                raise RuntimeError('unreachable')
        except providers.BrokerError as err:
            await audit.publish(
                [
                    _event(
                        'secret_resolution_denied',
                        context_row,
                        result='denied',
                        reason=err.reason,
                    )
                ]
            )
            raise
        await audit.publish([_event('secret_resolution_allowed', row)])
        return created

    async def _create(
        self, context: ResolutionContext, request: ResolutionRequest
    ) -> tuple[Created, Row]:
        if not (
            context.organization_id
            and context.agent_id
            and context.runner_id
            and context.task_id
        ):
            raise providers.BrokerError(
                'secret_access_denied', 'missing_context'
            )
        reference = parse_reference(request.reference)
        target = check_delivery(request.delivery_mode, request.delivery_target)
        handle = _new_handle()
        async with self._pool.connection() as conn, conn.transaction():
            await _check_task(conn, context)
            if request.idempotency_key:
                existing = await _fetch_one(
                    conn,
                    'SELECT *, expires_at <= NOW() AS expired'
                    ' FROM secrets.resolutions'
                    ' WHERE task_id = %s AND idempotency_key = %s'
                    ' FOR UPDATE',
                    (context.task_id, request.idempotency_key),
                )
                if existing is not None:
                    return await self._repeat(
                        conn,
                        existing,
                        context,
                        request,
                        str(reference),
                        handle,
                    )
            decision = await evaluate(
                conn,
                context.organization_id,
                context.agent_id,
                context.project_id,
                reference,
                request.purpose,
                request.delivery_mode,
                request.ttl_seconds,
            )
            row = await _fetch_one(
                conn,
                'INSERT INTO secrets.resolutions (id, organization_id,'
                ' binding_id, grant_id, provider_id, reference, field,'
                ' agent_id, project_id, task_id, runner_id, purpose,'
                ' delivery_mode, delivery_target, ttl_seconds, handle_hash,'
                ' idempotency_key, expires_at) VALUES (%s, %s, %s, %s, %s,'
                ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
                ' NOW() + make_interval(secs => %s)) RETURNING *',
                (
                    uuid.uuid4(),
                    context.organization_id,
                    decision.binding['id'],
                    decision.grant['id'],
                    decision.provider['id'],
                    str(reference),
                    reference.field,
                    context.agent_id,
                    context.project_id,
                    context.task_id,
                    context.runner_id,
                    request.purpose,
                    request.delivery_mode,
                    target,
                    request.ttl_seconds,
                    _digest(_HANDLE_LABEL, handle),
                    request.idempotency_key,
                    request.ttl_seconds,
                ),
            )
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError('resolution insert returned no row')
        return _created(row, handle), row

    async def _repeat(
        self,
        conn: Conn,
        row: Row,
        context: ResolutionContext,
        request: ResolutionRequest,
        reference: str,
        handle: str,
    ) -> tuple[Created, Row]:
        """Give an unused resolution a new handle for a repeat."""
        if (
            row['runner_id'],
            row['reference'],
            row['purpose'],
            row['delivery_mode'],
            row['delivery_target'],
            row['ttl_seconds'],
        ) != (
            context.runner_id,
            reference,
            request.purpose,
            request.delivery_mode,
            check_delivery(request.delivery_mode, request.delivery_target),
            request.ttl_seconds,
        ):
            raise providers.BrokerError(
                'resolution_context_mismatch', 'idempotency_key_reused'
            )
        if row['state'] == 'expired' or row['expired']:
            raise providers.BrokerError('resolution_expired')
        if row['state'] != 'active' or row['materialization_count']:
            raise providers.BrokerError('resolution_already_used')
        await conn.execute(
            'UPDATE secrets.resolutions SET handle_hash = %s WHERE id = %s',
            (_digest(_HANDLE_LABEL, handle), row['id']),
        )
        return _created(row, handle), row

    async def materialize(
        self, executor: ExecutorContext, request: MaterializeRequest
    ) -> Materialization:
        """Return the material of a resolution, at most its limit times.

        The handle and the nonce are consumed in one transaction before
        the provider call, so concurrent calls cannot both succeed. A
        provider failure marks the resolution ``failed``: the runner
        asks for a new one.

        Raises:
            BrokerError: The handle is not valid, the context does not
                match, a resource is disabled, or the provider failed.

        """
        row: Row | None = None
        try:
            async with self._pool.connection() as conn, conn.transaction():
                row = await _fetch_one(
                    conn,
                    'SELECT *, expires_at <= NOW() AS expired'
                    ' FROM secrets.resolutions WHERE handle_hash = %s'
                    ' FOR UPDATE',
                    (_digest(_HANDLE_LABEL, request.handle),),
                )
                if row is None:
                    raise providers.BrokerError('resolution_not_found')
                decision = await self._check_materialize(
                    conn, row, executor, request
                )
                await conn.execute(
                    'UPDATE secrets.resolutions'
                    ' SET materialization_count = materialization_count + 1,'
                    ' last_materialized_at = NOW() WHERE id = %s',
                    (row['id'],),
                )
        except providers.BrokerError as err:
            if row is not None:
                await audit.publish(
                    [
                        _event(
                            'secret_materialized',
                            row,
                            result='denied',
                            reason=err.reason,
                        )
                    ]
                )
            raise
        material = await self._resolve(row, decision)
        await audit.publish([_event('secret_materialized', row)])
        return Materialization(row, material)

    async def _check_materialize(
        self,
        conn: Conn,
        row: Row,
        executor: ExecutorContext,
        request: MaterializeRequest,
    ) -> Decision:
        if row['runner_id'] != executor.runner_id or (
            row['task_id'],
            row['agent_id'],
            row['project_id'],
            row['purpose'],
        ) != (
            request.task_id,
            request.agent_id,
            request.project_id,
            request.purpose,
        ):
            raise providers.BrokerError('resolution_context_mismatch')
        if row['state'] == 'expired' or row['expired']:
            raise providers.BrokerError('resolution_expired')
        if (
            row['state'] != 'active'
            or row['materialization_count'] >= row['materialization_limit']
        ):
            raise providers.BrokerError('resolution_already_used')
        cur = await conn.execute(
            'INSERT INTO secrets.nonces (nonce_hash, resolution_id)'
            ' VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING 1',
            (_digest(_NONCE_LABEL, request.nonce), row['id']),
        )
        if await cur.fetchone() is None:
            raise providers.BrokerError(
                'resolution_already_used', 'nonce_replay'
            )
        # The current state of the task and every resource, not the
        # state at create.
        await _check_task(
            conn,
            ResolutionContext(
                organization_id=row['organization_id'],
                agent_id=row['agent_id'],
                project_id=row['project_id'],
                task_id=row['task_id'],
                runner_id=row['runner_id'],
            ),
        )
        reference = parse_reference(row['reference'])
        binding = _check_binding(
            await _fetch_one(
                conn,
                'SELECT * FROM secrets.bindings WHERE id = %s',
                (row['binding_id'],),
            ),
            reference,
        )
        if (
            binding['reference'] != reference.binding
            or binding['provider_id'] != row['provider_id']
            or row['delivery_mode'] not in binding['allowed_delivery_modes']
        ):
            raise providers.BrokerError(
                'secret_access_denied', 'binding_changed'
            )
        provider = _check_provider(
            await _fetch_one(
                conn,
                'SELECT * FROM secrets.providers WHERE id = %s',
                (row['provider_id'],),
            ),
            binding,
        )
        grant = await _fetch_one(
            conn,
            _GRANT_MATCH + ' AND id = %(grant)s',
            {
                'org': row['organization_id'],
                'binding': row['binding_id'],
                'agent': row['agent_id'],
                'purpose': row['purpose'],
                'mode': row['delivery_mode'],
                'project': row['project_id'],
                'grant': row['grant_id'],
            },
        )
        if grant is None:
            raise providers.BrokerError(
                'secret_access_denied', 'grant_changed'
            )
        return Decision(binding, provider, grant)

    async def _resolve(
        self, row: Row, decision: Decision
    ) -> providers.Material:
        """Call the provider and keep its lease. Marks a failure."""
        plugin = providers.get(decision.provider['type'])
        config = decision.provider['config']
        try:
            material = await plugin.resolve(
                config,
                decision.binding['locator'],
                row['field'],
                providers.ResolveContext(
                    organization_id=row['organization_id'],
                    task_id=row['task_id'],
                    project_id=row['project_id'],
                    purpose=row['purpose'],
                    ttl_seconds=row['ttl_seconds'],
                    credential_class=decision.binding['credential_class'],
                ),
            )
            now = datetime.datetime.now(datetime.UTC)
            if material.lease_id is not None:
                await self._save_lease(row, plugin, config, material)
            if (
                material.credential_expires_at is not None
                and material.credential_expires_at <= now
            ):
                raise providers.BrokerError(
                    'secret_materialization_failed', 'credential_expired'
                )
        except providers.BrokerError as err:
            await self._fail(row, err)
            raise
        except Exception as exc:  # noqa: BLE001 - translated below
            # The type only: a provider message could hold a value.
            LOGGER.error(
                'Provider %s failed: %s',
                decision.provider['type'],
                type(exc).__name__,
            )
            failure = providers.BrokerError(
                'secret_materialization_failed', 'provider_error'
            )
            await self._fail(row, failure)
            raise failure from None
        return material

    async def _save_lease(
        self,
        row: Row,
        plugin: providers.Provider,
        config: dict[str, typing.Any],
        material: providers.Material,
    ) -> None:
        """Store the encrypted lease id. If that fails, revoke at once."""
        lease_id = typing.cast(str, material.lease_id)
        try:
            async with self._pool.connection() as conn:
                await conn.execute(
                    'UPDATE secrets.resolutions SET lease_id = %s,'
                    ' revocation_state = %s, credential_expires_at = %s'
                    ' WHERE id = %s',
                    (
                        encryption.encrypt_token(lease_id),
                        'pending' if material.revocable else 'not_applicable',
                        material.credential_expires_at,
                        row['id'],
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - revoked and reported
            # No traceback anywhere here: frames hold the lease id.
            LOGGER.error(
                'Resolution %s: lease not saved: %s',
                row['id'],
                type(exc).__name__,
            )
            if material.revocable:
                try:
                    await plugin.revoke(config, lease_id)
                except Exception:  # noqa: BLE001 - reported below
                    LOGGER.error(
                        'Resolution %s: unsaved lease not revoked', row['id']
                    )
            raise providers.BrokerError(
                'secret_materialization_failed', 'lease_not_saved'
            ) from None

    async def _fail(self, row: Row, err: providers.BrokerError) -> None:
        try:
            async with self._pool.connection() as conn:
                await conn.execute(
                    "UPDATE secrets.resolutions SET state = 'failed',"
                    ' failure_reason = %s, handle_hash = NULL'
                    " WHERE id = %s AND state = 'active'",
                    (err.reason, row['id']),
                )
        except Exception as exc:  # noqa: BLE001 - the handle is used up
            LOGGER.error(
                'Resolution %s: state not saved: %s',
                row['id'],
                type(exc).__name__,
            )
        await audit.publish(
            [
                _event(
                    'secret_materialized',
                    row,
                    result='failed',
                    reason=err.reason,
                )
            ]
        )

    async def release(
        self,
        resolution_id: uuid.UUID,
        *,
        reason: str,
        actor: str,
        organization_id: str | None = None,
        runner_id: str | None = None,
    ) -> Row:
        """Release a resolution and revoke its provider lease.

        Idempotent. ``organization_id`` scopes a management call and
        ``runner_id`` an executor call. A revocation failure does not
        fail the release: it stays ``failed`` on the row.

        Raises:
            BrokerError: ``resolution_not_found``.

        """
        async with self._pool.connection() as conn, conn.transaction():
            row = await _fetch_one(
                conn,
                'SELECT * FROM secrets.resolutions WHERE id = %s'
                ' AND (%s::TEXT IS NULL OR organization_id = %s)'
                ' AND (%s::TEXT IS NULL OR runner_id = %s) FOR UPDATE',
                (
                    resolution_id,
                    organization_id,
                    organization_id,
                    runner_id,
                    runner_id,
                ),
            )
            if row is None:
                raise providers.BrokerError('resolution_not_found')
            released = row['state'] in ('pending', 'active')
            if released:
                row = await _fetch_one(
                    conn,
                    "UPDATE secrets.resolutions SET state = 'released',"
                    ' handle_hash = NULL, released_at = NOW(),'
                    ' release_reason = %s WHERE id = %s RETURNING *',
                    (reason, resolution_id),
                )
        row = typing.cast(Row, row)
        if released:
            await audit.publish(
                [_event('secret_resolution_released', row, actor=actor)]
            )
        if row['revocation_state'] in ('pending', 'failed'):
            await self._revoke(row, actor)
        return typing.cast(Row, await self.get(row['id']))

    async def revoke_provider_lease(
        self, organization_id: str, resolution_id: uuid.UUID, actor: str
    ) -> Row:
        """Revoke the provider lease of a resolution now.

        Raises:
            BrokerError: ``resolution_not_found``,
                ``provider_lease_not_revocable``, or
                ``provider_revocation_failed``.

        """
        row = await self.get(resolution_id)
        if row is None or row['organization_id'] != organization_id:
            raise providers.BrokerError('resolution_not_found')
        if row['revocation_state'] == 'not_applicable':
            raise providers.BrokerError('provider_lease_not_revocable')
        if row['revocation_state'] != 'succeeded' and not await self._revoke(
            row, actor
        ):
            raise providers.BrokerError('provider_revocation_failed')
        return typing.cast(Row, await self.get(resolution_id))

    async def _revoke(self, row: Row, actor: str = 'system') -> bool:
        """Revoke a provider lease and record the result."""
        reason = None
        try:
            async with self._pool.connection() as conn:
                provider = await _fetch_one(
                    conn,
                    'SELECT * FROM secrets.providers WHERE id = %s',
                    (row['provider_id'],),
                )
            if provider is None:
                raise providers.BrokerError(
                    'provider_revocation_failed', 'no_provider'
                )
            await providers.get(provider['type']).revoke(
                provider['config'],
                encryption.decrypt_token(typing.cast(str, row['lease_id'])),
            )
        except providers.BrokerError as err:
            reason = err.reason
        except Exception as exc:  # noqa: BLE001 - recorded as failed
            # No traceback: the provider frames hold the lease id.
            LOGGER.error(
                'Resolution %s: revocation failed: %s',
                row['id'],
                type(exc).__name__,
            )
            reason = 'provider_error'
        async with self._pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.resolutions SET revocation_state = %s,'
                ' revocation_reason = %s, revocation_attempted_at = NOW()'
                ' WHERE id = %s',
                ('failed' if reason else 'succeeded', reason, row['id']),
            )
        await audit.publish(
            [
                _event(
                    'secret_lease_revocation_failed'
                    if reason
                    else 'secret_lease_revoked',
                    row,
                    result='failed' if reason else 'succeeded',
                    reason=reason or '',
                    actor=actor,
                )
            ]
        )
        return reason is None

    async def release_runner_resolutions(self, runner_id: str) -> bool:
        """Release every open resolution of a runner and revoke leases.

        For fencing (ADR 0022): return ``True`` only when no provider
        lease of the runner is left unrevoked.
        """
        async with self._pool.connection() as conn:
            released = await _fetch(
                conn,
                "UPDATE secrets.resolutions SET state = 'released',"
                ' handle_hash = NULL, released_at = NOW(),'
                " release_reason = 'runner_fenced'"
                " WHERE runner_id = %s AND state IN ('pending', 'active')"
                ' RETURNING *',
                (runner_id,),
            )
            pending = await _fetch(
                conn,
                'SELECT * FROM secrets.resolutions WHERE runner_id = %s'
                " AND revocation_state IN ('pending', 'failed')",
                (runner_id,),
            )
        await audit.publish(
            [
                _event('secret_resolution_released', row, actor='system')
                for row in released
            ]
        )
        ok = True
        for row in pending:
            ok = await self._revoke(row) and ok
        return ok

    async def sweep(self) -> int:
        """Expire resolutions past ``expires_at``, release the open
        resolutions of closed tasks, and retry revocations.

        Return the number expired. A row is returned by one ``UPDATE``
        only, so concurrent sweeps do not change a row twice.
        """
        async with self._pool.connection() as conn:
            expired = await _fetch(
                conn,
                "UPDATE secrets.resolutions SET state = 'expired',"
                ' handle_hash = NULL'
                " WHERE state IN ('pending', 'active')"
                ' AND expires_at <= NOW() RETURNING *',
                (),
            )
            # No hook runs when a task closes, so the sweep releases
            # what its task left open. Materialize refuses them already.
            closed = await _fetch(
                conn,
                "UPDATE secrets.resolutions AS r SET state = 'released',"
                ' handle_hash = NULL, released_at = NOW(),'
                " release_reason = 'task_closed'"
                ' FROM agent_runtime.tasks AS t'
                " WHERE t.id = r.task_id AND t.status = 'closed'"
                " AND r.state IN ('pending', 'active') RETURNING r.*",
                (),
            )
            retry = await _fetch(
                conn,
                'SELECT * FROM secrets.resolutions'
                " WHERE revocation_state IN ('pending', 'failed')"
                " AND state IN ('released', 'expired', 'failed')"
                ' AND COALESCE(revocation_attempted_at, released_at,'
                " expires_at) < NOW() - INTERVAL '60 seconds'"
                ' ORDER BY created_at LIMIT 100',
                (),
            )
        await audit.publish(
            [
                _event('secret_resolution_expired', row, actor='system')
                for row in expired
            ]
            + [
                _event('secret_resolution_released', row, actor='system')
                for row in closed
            ]
        )
        for row in expired + closed:
            if row['revocation_state'] == 'pending':
                await self._revoke(row)
        for row in retry:
            await self._revoke(row)
        return len(expired)

    async def get(self, resolution_id: uuid.UUID) -> Row | None:
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                'SELECT * FROM secrets.resolutions WHERE id = %s',
                (resolution_id,),
            )


def _created(row: Row, handle: str) -> Created:
    return Created(
        resolution_id=row['id'],
        handle=handle,
        state=row['state'],
        expires_at=row['expires_at'],
        delivery_mode=row['delivery_mode'],
        delivery_target=row['delivery_target'],
    )
