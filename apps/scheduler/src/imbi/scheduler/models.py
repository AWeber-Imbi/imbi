"""Domain models for scheduled tasks.

The scheduler triggers; it does not execute. Every task therefore reduces to
four things: when it fires (`trigger`), who it fires as (`identity`), what it
calls (`target`), and how failures are handled (`execution`).

Per ADR 0002 there is no credential store and no arbitrary-URL target, so a
task can only ever call `imbi-api` or `imbi-gateway` — which means every run
is attributable by construction.
"""

import datetime
import re
import typing
import uuid
import zoneinfo

import httpx
import pydantic

from imbi.scheduler import triggers

#: Slugs are lowercase kebab-case, matching the platform's other slugs.
SLUG_PATTERN = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')

SLUG_MAX_LENGTH = 64

#: Run states. `no_effect` is terminal and distinct from success: a gateway
#: 204 means the delivery was accepted and then dropped, and recording that as
#: a success would hide a task that silently does nothing forever.
RunState = typing.Literal[
    'running',
    'succeeded',
    'no_effect',
    'failed',
    'timed_out',
    'skipped',
    'cancelled',
]

TERMINAL_RUN_STATES: frozenset[str] = frozenset(
    {
        'succeeded',
        'no_effect',
        'failed',
        'timed_out',
        'skipped',
        'cancelled',
    }
)

HttpMethod = typing.Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

#: Gateway deliveries carry their disposition in the status code.
GATEWAY_ACCEPTED = 202
GATEWAY_DROPPED = 204


def ensure_slug(value: str) -> str:
    """Return `value`, or raise unless it is a bare kebab-case slug."""
    if len(value) > SLUG_MAX_LENGTH:
        raise ValueError(f'must be at most {SLUG_MAX_LENGTH} characters')
    if not SLUG_PATTERN.match(value):
        raise ValueError(
            'must be lowercase alphanumeric with interior hyphens'
        )
    return value


def ensure_no_traversal(path: str) -> str:
    """Return `path`, or raise if it could address anything above itself.

    Load-bearing rather than defensive. :func:`imbi.scheduler.render.
    api_request` confines an organization-scoped task by prefixing
    ``/organizations/<slug>``, and it decides whether the prefix is needed by
    string comparison — *before* anything normalizes the path. ``httpx``
    resolves ``..`` client-side, so ``/../../admin/users`` on a task scoped to
    ``acme`` leaves as ``/admin/users``: the scoping is defeated and the
    request still carries the scheduler's service-account credential.

    Separators are rejected outright rather than decoded, because decoding is
    a game this side cannot win. An earlier version of this function split on
    ``/`` and *then* decoded each piece, which let ``/..%2fadmin/users``
    through — the encoded slash kept the segment whole, so it never equalled
    ``'..'`` — and ``%252e`` needs two passes before it even looks like a dot.
    Any rule of that shape is only as good as the encodings someone thought
    to enumerate.

    So: no ``%`` and no backslash anywhere in a path, and no literal ``.`` or
    ``..`` segment. These are internal `imbi-api` paths addressing
    kebab-case slugs, so an author loses nothing they can legitimately want,
    and the entire encoded-separator class stops existing rather than being
    chased. ``httpx`` passes both characters through untouched, which means
    whether they traverse would otherwise be decided by the receiving
    server — and which routes a task can reach must not be a property of
    something that far away.
    """
    for forbidden, why in (
        ('%', 'percent-encoding'),
        ('\\', 'a backslash'),
    ):
        if forbidden in path:
            raise ValueError(
                f'path may not contain {why}: an encoded separator is '
                'indistinguishable from a traversal by the time it reaches '
                'the server'
            )
    for segment in path.split('/'):
        if segment in {'.', '..'}:
            raise ValueError(
                f'path may not contain the traversal segment {segment!r}'
            )
    return path


class Identity(pydantic.BaseModel):
    """The principal a task runs as.

    Resolved at fire time, never at creation time, so revoking consent or
    deactivating a user stops future runs without touching the task.
    """

    kind: typing.Literal['delegated_user', 'service_account']
    subject: str
    consent_id: str | None = None
    scope: str = 'imbi-api:*'

    @pydantic.model_validator(mode='after')
    def _validate_consent(self) -> typing.Self:
        if self.kind == 'delegated_user' and not self.consent_id:
            raise ValueError('delegated_user identity requires a consent_id')
        if self.kind == 'service_account' and self.consent_id:
            raise ValueError(
                'consent_id is meaningful only for delegated_user identity'
            )
        return self


class ApiTarget(pydantic.BaseModel):
    """An `imbi-api` request made as the task's identity."""

    kind: typing.Literal['api'] = 'api'
    method: HttpMethod
    path: str
    query: dict[str, str] = {}
    body: dict[str, typing.Any] | None = None
    organization: str | None = None

    #: An api call is made *as* somebody, so it needs a principal.
    requires_identity: typing.ClassVar[bool] = True

    def summary(self) -> str:
        """Return a short, loggable description of this target."""
        return f'{self.method} {self.path}'

    def classify(
        self, response: httpx.Response
    ) -> typing.Literal['succeeded', 'no_effect', 'failed']:
        """Map a response to a terminal run state."""
        return 'succeeded' if response.is_success else 'failed'

    def principal(self) -> str:
        """Raise: an api target always runs as somebody.

        Unreachable while the task validator holds. Raising rather than
        inventing a label means a lapse in that validator surfaces loudly
        instead of writing a fictional principal into run history.
        """
        raise RuntimeError('api targets always carry an identity')

    @pydantic.field_validator('path')
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if '://' in value or value.startswith('//'):
            raise ValueError(
                'path must be relative to the API base URL, not absolute'
            )
        if not value.startswith('/'):
            raise ValueError('path must begin with /')
        # Also checked on the *rendered* path at fire time, because this
        # value is a Jinja template and a traversal can arrive from the
        # context rather than the source. Kept here as well so an author gets
        # a 422 at create time rather than a failed run months later.
        return ensure_no_traversal(value)

    @pydantic.field_validator('organization')
    @classmethod
    def _validate_organization(cls, value: str | None) -> str | None:
        # Interpolated straight into the path by `render.api_request`, so a
        # slash or dot-segment here is the same escape by another door.
        return None if value is None else ensure_slug(value)


class GatewayTarget(pydantic.BaseModel):
    """A webhook delivery to `imbi-gateway`.

    The gateway endpoint has no bearer check and derives attribution from the
    payload, so a delegated token would be meaningless to it. Attribution is
    the payload's job; the run records `gateway:<webhook_id>` as its
    principal and leaves user attribution to the event the gateway writes.
    """

    kind: typing.Literal['gateway'] = 'gateway'
    webhook_id: str
    payload: dict[str, typing.Any]
    headers: dict[str, str] = {}

    #: The endpoint has no bearer check, so a credential would be theater.
    requires_identity: typing.ClassVar[bool] = False

    def summary(self) -> str:
        """Return a short, loggable description of this target."""
        return f'POST /notifications/{self.webhook_id}'

    def principal(self) -> str:
        """Return the principal recorded for an identity-less delivery."""
        return f'gateway:{self.webhook_id}'

    def classify(
        self, response: httpx.Response
    ) -> typing.Literal['succeeded', 'no_effect', 'failed']:
        """Map a response to a terminal run state.

        202 means accepted and handled; 204 means accepted and then dropped
        — no matching webhook, no project resolved, or no rule matched.
        Recording that as success would hide a task that silently does
        nothing forever, so it gets its own terminal state.
        """
        if response.status_code == GATEWAY_ACCEPTED:
            return 'succeeded'
        if response.status_code == GATEWAY_DROPPED:
            return 'no_effect'
        return 'failed'

    @pydantic.field_validator('webhook_id')
    @classmethod
    def _validate_webhook_id(cls, value: str) -> str:
        # `render.gateway_request` interpolates this into
        # `/notifications/<id>`, so an unconstrained value walks out of that
        # path the same way an api target's would.
        return ensure_slug(value)


Target = typing.Annotated[
    ApiTarget | GatewayTarget, pydantic.Field(discriminator='kind')
]


class ExecutionPolicy(pydantic.BaseModel):
    """How a firing is attempted and what happens when it fails.

    `timeout` defaults to two minutes rather than something generous: every
    target is one HTTP call, and a trigger endpoint is expected to enqueue
    rather than block.

    There is no `coalesce` flag: one claim per due timestamp means a task that
    fell behind fires once on catch-up rather than once per missed interval, so
    coalescing is not optional behavior to configure.
    """

    misfire_grace_time: int | None = 300
    max_running_instances: int = 1
    timeout: int = 120
    retries: int = 0
    retry_backoff: typing.Literal['none', 'linear', 'exponential'] = (
        'exponential'
    )
    idempotency_key: str | None = None

    @pydantic.model_validator(mode='after')
    def _validate_bounds(self) -> typing.Self:
        if self.timeout <= 0:
            raise ValueError('timeout must be greater than zero')
        if self.retries < 0:
            raise ValueError('retries must not be negative')
        if self.max_running_instances < 1:
            raise ValueError('max_running_instances must be at least one')
        if self.misfire_grace_time is not None and self.misfire_grace_time < 0:
            raise ValueError('misfire_grace_time must not be negative')
        return self


class Task(pydantic.BaseModel):
    """A scheduled task definition."""

    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    organization: str | None = None
    enabled: bool = True
    kind: typing.Literal['system', 'user']
    trigger: triggers.Trigger
    timezone: str = 'UTC'
    identity: Identity | None = None
    target: Target
    execution: ExecutionPolicy = ExecutionPolicy()
    tags: list[str] = []
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    last_run_at: datetime.datetime | None = None
    next_run_at: datetime.datetime | None = None
    consecutive_skips: int = 0
    consecutive_no_effect: int = 0

    @pydantic.field_validator('slug')
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        return ensure_slug(value)

    @pydantic.field_validator('organization')
    @classmethod
    def _validate_organization(cls, value: str | None) -> str | None:
        # The fallback scope `render.api_request` uses when the target names
        # no organization of its own, and interpolated into the path exactly
        # the same way.
        return None if value is None else ensure_slug(value)

    @pydantic.field_validator('timezone')
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f'unknown IANA timezone: {value}') from err
        return value

    @pydantic.model_validator(mode='after')
    def _validate_identity_matches_target(self) -> typing.Self:
        """Require an identity exactly when the target needs one.

        One symmetric check driven by the target, so a new target kind
        declares its own rule rather than being added to two conditions here.
        """
        if self.target.requires_identity and self.identity is None:
            raise ValueError(f'{self.target.kind} targets require an identity')
        if not self.target.requires_identity and self.identity is not None:
            raise ValueError(
                f'{self.target.kind} targets carry no identity: the endpoint '
                'has no bearer check and derives attribution from the payload'
            )
        return self

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        """Return the task's timezone."""
        return zoneinfo.ZoneInfo(self.timezone)

    @property
    def principal_name(self) -> str:
        """Return who this task runs as, for the run record."""
        if self.identity is not None:
            return self.identity.subject
        return self.target.principal()

    def next_fire_time(
        self, after: datetime.datetime
    ) -> datetime.datetime | None:
        """Return the first firing strictly after `after`."""
        return self.trigger.next_fire_time(after, self.tzinfo)

    def target_summary(self) -> str:
        """Return a short, loggable description of the target."""
        return self.target.summary()
