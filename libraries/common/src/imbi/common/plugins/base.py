"""Plugin base classes and shared data models.

Plugin Architecture v3 (``api_version = 2``): a Python package ships
exactly one :class:`Plugin` whose :class:`PluginManifest` declares the
package's integration-level options and credentials **once**, plus a set
of :class:`Capability` entries. Each capability binds an implementation
(a :class:`CapabilityHandler` subclass) for one enumerated
:data:`CapabilityKind`. There is no per-capability credential
declaration and no ``connection`` plugin — the Integration node *is* the
connection.
"""

import abc
import collections.abc
import datetime
import typing

import pydantic

from imbi_common.plugins.errors import PluginRemediationNotSupported


class PluginOption(pydantic.BaseModel):
    name: str
    label: str
    description: str | None = None
    #: ``mapping`` renders a key/value editor in the admin UI and stores
    #: the resolved value as a ``dict[str, str]`` rather than a scalar.
    type: typing.Literal[
        'string', 'integer', 'boolean', 'secret', 'mapping'
    ] = 'string'
    required: bool = False
    default: str | int | bool | dict[str, str] | None = None
    choices: list[str] | None = None

    @pydantic.model_validator(mode='after')
    def _validate_mapping_shape(self) -> PluginOption:
        if self.type == 'mapping':
            if self.choices is not None:
                raise ValueError(
                    "PluginOption.choices is not supported for type='mapping'"
                )
            if self.default is not None and not isinstance(self.default, dict):
                raise ValueError(
                    "PluginOption.default for type='mapping' must be a "
                    'dict[str, str]'
                )
        elif isinstance(self.default, dict):
            raise ValueError(
                "PluginOption.default may only be a dict when type='mapping'"
            )
        return self


class CredentialField(pydantic.BaseModel):
    name: str
    label: str
    description: str | None = None
    required: bool = True


class DataType(pydantic.BaseModel):
    name: str
    label: str
    secret: bool = False


class PluginIndex(pydantic.BaseModel):
    fields: list[str]
    unique: bool = False

    @pydantic.field_validator('fields')
    @classmethod
    def _validate_fields(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError(
                'PluginIndex.fields must contain at least one field name'
            )
        for field in value:
            if not field or not field.strip():
                raise ValueError(
                    'PluginIndex.fields entries must be non-empty and '
                    'non-whitespace'
                )
        return value


class PluginVertexLabel(pydantic.BaseModel):
    name: str
    indexes: list[PluginIndex] = []
    model_ref: str
    # Operator-facing display fields.  ``name`` stays the canonical
    # graph-label identifier; these provide friendlier UI text and can
    # be overridden per-installation via ``PluginRegistration``.
    #
    # * ``display_name``  — page header / detail card title
    #                       (e.g. "AWS Accounts")
    # * ``description``   — sentence-or-two operator help text
    # * ``nav_label``     — sidebar entry text (defaults to display_name
    #                        when unset, then to ``name``)
    display_name: str | None = None
    description: str | None = None
    nav_label: str | None = None


class PluginEdgeLabel(pydantic.BaseModel):
    name: str
    from_labels: list[str]
    to_labels: list[str]
    properties: dict[str, str] = {}


class OpsLogTemplate(pydantic.BaseModel):
    """Plugin-supplied formatter for an operations-log entry.

    Keyed off the ``action`` value the API writes into the ops-log
    ``description`` payload (e.g. ``promote`` / ``deploy`` for
    deployment capabilities, ``set_value`` / ``delete_key`` for config
    capabilities).  The UI substitutes ``{{name}}`` placeholders against
    the payload merged with row-level fields (``version``,
    ``environment``, ``project``, ``performer``).
    """

    label: str
    summary: str | None = None


# ---------------------------------------------------------------------------
# Capability kinds and surfaces
# ---------------------------------------------------------------------------

#: The surface a capability presents to the platform.
CapabilitySurface = typing.Literal[
    'ui',  # renders in imbi-ui (project tab, panel, admin card)
    'api',  # host-invoked behavior (lifecycle hooks, deploy actions)
    'webhook',  # dispatched by imbi-gateway from inbound deliveries
    'tools',  # exposes agent-consumable tools (imbi-assistant / imbi-mcp)
]

#: Enumerated capability kinds. Each maps to exactly one contract ABC
#: (:data:`CAPABILITY_CONTRACTS`) and a fixed surface classification
#: (:data:`CAPABILITY_SURFACES`). Adding a kind is a base-model change,
#: deliberately — the platform must know how to host it.
CapabilityKind = typing.Literal[
    'configuration',  # project config store        → ui, api
    'logs',  # log search                  → ui, api
    'identity',  # per-user auth to the remote → api
    'deployment',  # refs/commits/deploys        → ui, api
    'lifecycle',  # project state mirroring     → api
    'webhook-actions',  # gateway action catalog      → webhook
    'analysis',  # project doctor findings     → ui, api
    'incidents',  # incidents tab               → ui, api
    'commit-sync',  # commit history ingestion    → api, webhook
    'pr-sync',  # pull-request ingestion      → api, webhook
    'tools',  # agent tools (reserved)      → tools
]

CAPABILITY_SURFACES: dict[str, frozenset[str]] = {
    'configuration': frozenset({'ui', 'api'}),
    'logs': frozenset({'ui', 'api'}),
    'identity': frozenset({'api'}),
    'deployment': frozenset({'ui', 'api'}),
    'lifecycle': frozenset({'api'}),
    'webhook-actions': frozenset({'webhook'}),
    'analysis': frozenset({'ui', 'api'}),
    'incidents': frozenset({'ui', 'api'}),
    'commit-sync': frozenset({'api', 'webhook'}),
    'pr-sync': frozenset({'api', 'webhook'}),
    'tools': frozenset({'tools'}),
}

#: ``cacheable`` is accepted for every kind (v1 default ``True`` carries
#: over — a hint the host may consult to cache a capability's reads).
_COMMON_HINTS: frozenset[str] = frozenset({'cacheable'})

#: Per-kind allowlist of accepted :attr:`Capability.hints` keys. Kind
#: hints that were manifest booleans in v1 move here; an unknown key
#: fails at manifest construction so typos surface at load.
HINT_ALLOWLIST: dict[str, frozenset[str]] = {
    'configuration': _COMMON_HINTS,
    'logs': _COMMON_HINTS | frozenset({'supports_histogram'}),
    'identity': _COMMON_HINTS
    | frozenset({'login_capable', 'default_scopes', 'widget_text'}),
    'deployment': _COMMON_HINTS | frozenset({'supports_deployment_sync'}),
    'lifecycle': _COMMON_HINTS
    | frozenset({'supports_lifecycle_sync', 'lifecycle_events'}),
    'webhook-actions': _COMMON_HINTS,
    'analysis': _COMMON_HINTS,
    'incidents': _COMMON_HINTS,
    'commit-sync': _COMMON_HINTS,
    'pr-sync': _COMMON_HINTS,
    'tools': _COMMON_HINTS,
}


class Capability(pydantic.BaseModel):
    """One capability of a plugin — declaration plus handler binding.

    A ``Capability`` both **declares** operator-facing metadata (label,
    options, defaults) and **binds** the implementation via
    :attr:`handler`, mirroring how :class:`ActionDescriptor` binds a
    webhook action's ``callable``. It is validated at construction: the
    handler must subclass the contract ABC for :attr:`kind`
    (:data:`CAPABILITY_CONTRACTS`) and every :attr:`hints` key must be in
    the per-kind allowlist (:data:`HINT_ALLOWLIST`).
    """

    kind: CapabilityKind
    label: str
    description: str | None = None
    #: Capability-scoped options, rendered under the capability's toggle
    #: in the Integration form. Values live in
    #: ``Integration.capabilities[kind].options``.
    options: list[PluginOption] = []
    #: Initial toggle state when an Integration is created.
    default_enabled: bool = True
    #: Whether the capability participates in per-project-type /
    #: per-project ``USES`` assignment (identity, for example, does not —
    #: it is Integration-wide).
    project_scoped: bool = True
    #: Capability wants ``ctx.identity`` populated when available.
    requires_identity: bool = False
    #: Kind-specific hints (validated against :data:`HINT_ALLOWLIST`):
    #: ``supports_histogram`` (logs), ``supports_deployment_sync``
    #: (deployment), ``supports_lifecycle_sync`` + ``lifecycle_events``
    #: (lifecycle), ``login_capable`` + ``default_scopes`` +
    #: ``widget_text`` (identity), ``cacheable`` (any kind).
    hints: dict[str, typing.Any] = {}
    #: RESERVED: package-relative path to a built ESM module the UI can
    #: load for this capability. ``None`` = use built-in UI.
    ui_module: str | None = None
    #: The implementation — a class subclassing the contract ABC for
    #: :attr:`kind`. Excluded from serialization: the manifest that
    #: reaches the API/UI is pure data.
    handler: typing.Annotated[
        type,
        pydantic.Field(exclude=True, repr=False),
    ]

    @property
    def surfaces(self) -> frozenset[str]:
        """The surfaces this capability presents (per its kind)."""
        return CAPABILITY_SURFACES[self.kind]

    @pydantic.model_validator(mode='after')
    def _validate_handler_and_hints(self) -> Capability:
        contract = CAPABILITY_CONTRACTS[self.kind]
        if not (
            isinstance(self.handler, type)
            and issubclass(self.handler, contract)
        ):
            raise ValueError(
                f'Capability kind {self.kind!r} requires a handler '
                f'subclassing {contract.__name__}, got {self.handler!r}'
            )
        allowed = HINT_ALLOWLIST[self.kind]
        unknown = sorted(set(self.hints) - allowed)
        if unknown:
            raise ValueError(
                f'Capability kind {self.kind!r} got unknown hint keys '
                f'{unknown}; allowed: {sorted(allowed)}'
            )
        return self


class PluginManifest(pydantic.BaseModel):
    """The complete declaration of a plugin package.

    Integration-level options and credentials are declared **once**;
    capabilities are enabled/configured per Integration.
    """

    slug: str
    name: str
    description: str | None = None
    api_version: int = 2
    auth_type: typing.Literal[
        'api_token', 'oauth2', 'oidc', 'aws-iam-ic', 'none'
    ] = 'api_token'
    #: Integration-level options — asked ONCE per Integration
    #: (e.g. github: flavor, host; aws: region, default_role_name).
    options: list[PluginOption] = []
    #: Integration-level credentials — the ONLY credential declaration in
    #: the package. Capabilities cannot declare credentials. OAuth
    #: ``client_id`` / ``client_secret`` are ordinary named fields here.
    credentials: list[CredentialField] = []
    capabilities: list[Capability]
    #: Package-level extension points, unchanged in shape from v1.
    data_types: list[DataType] = []
    vertex_labels: list[PluginVertexLabel] = []
    edge_labels: list[PluginEdgeLabel] = []
    ops_log_templates: dict[str, OpsLogTemplate] = {}

    @pydantic.model_validator(mode='after')
    def _validate_capabilities(self) -> PluginManifest:
        if not self.capabilities:
            raise ValueError(
                'PluginManifest.capabilities must declare at least one '
                'capability'
            )
        seen: set[str] = set()
        duplicates: set[str] = set()
        for capability in self.capabilities:
            if capability.kind in seen:
                duplicates.add(capability.kind)
            seen.add(capability.kind)
        if duplicates:
            raise ValueError(
                f'PluginManifest declares duplicate capability kinds: '
                f'{sorted(duplicates)}'
            )
        return self

    def get_capability(self, kind: str) -> Capability | None:
        """Return the capability of ``kind``, or ``None`` when absent."""
        for capability in self.capabilities:
            if capability.kind == kind:
                return capability
        return None


class IdentityProfile(pydantic.BaseModel):
    """Normalized profile returned after a successful identity flow."""

    subject: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    avatar_url: str | None = None
    groups: list[str] = []
    raw_claims: dict[str, typing.Any] = {}


class IdentityCredentials(pydantic.BaseModel):
    """Materialized credentials handed to other capabilities.

    Capabilities receive this in :class:`PluginContext.identity` when the
    assignment declares an identity Integration.  The shape is close to
    the OAuth 2.0 RFC 6749 token response so most backends consume it
    directly.  ``extra`` carries backend-specific keys (e.g. STS temp
    credentials for AWS IAM IC).
    """

    access_token: str
    token_type: str = 'Bearer'
    expires_at: datetime.datetime | None = None
    refresh_token: str | None = None
    scopes: list[str] = []
    extra: dict[str, typing.Any] = {}

    def __repr__(self) -> str:
        return '<IdentityCredentials redacted>'

    def __str__(self) -> str:
        return '<IdentityCredentials redacted>'


class PollingDescriptor(pydantic.BaseModel):
    """Descriptor for device-flow style polling.

    Returned by identity capabilities whose authorization flow is not a
    redirect (e.g. AWS IAM Identity Center device authorization).  The
    UI polls ``/me/identities/{integration_id}/poll`` every ``interval``
    seconds, surfacing ``user_code`` to the user.
    """

    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    interval: int = 5
    expires_in: int


class AuthorizationRequest(pydantic.BaseModel):
    """What the API needs to redirect the browser to start a flow."""

    authorization_url: str
    state: str
    code_verifier: str | None = None
    polling: PollingDescriptor | None = None
    # Credentials the capability minted on the fly during this call (e.g.
    # an OIDC dynamic-client registration for AWS IAM IC).  The host
    # persists them to the Integration's encrypted credential blob so that
    # the matching ``exchange_code`` / ``refresh`` calls -- which receive
    # ``credentials`` from storage, not from this object — see the same
    # client identity.  ``None`` means "nothing new to persist".
    registered_credentials: dict[str, str] | None = None


class LinkWriteback(pydantic.BaseModel):
    """A project-link URL the host should persist on the project node.

    Set by a deployment / lifecycle capability on :class:`PluginContext`
    when the call mutated, created, or discovered the canonical URL for
    one of the project's external links.  Covers four cases:

    * **Create** -- a new repository was provisioned and the
      ``github-repository`` (or equivalent) link must be stored for the
      first time.
    * **Rename / 301** -- the remote answered a request to a renamed
      repo with a ``301`` to the canonical ``/repositories/{id}``
      location; the host self-heals the stored link so later calls skip
      the redirect and the UI shows the current name.
    * **Relocate / transfer** -- the repository moved to a new owner
      (e.g. ``POST /repos/{owner}/{repo}/transfer``) and the stored
      link must be rewritten to the new canonical URL.
    * **Discovery** -- the capability resolved a link the host had not
      yet stored (e.g. by following a redirect chain).

    Capabilities only ever *write* this field; it is not part of the
    inbound context the host populates.
    """

    #: Which ``PluginContext.project_links`` key the host should write.
    link_key: str
    #: Canonical URL (e.g. GitHub ``html_url``) to store under ``link_key``.
    new_url: str
    #: ``<owner>/<repo>`` the call started from -- informational / logging.
    old_owner_repo: str | None = None
    #: ``<owner>/<repo>`` the remote ended at -- informational.
    new_owner_repo: str | None = None


class ServiceConnection(pydantic.BaseModel):
    """A project's ``EXISTS_IN`` edge to an Integration.

    Populated by the host on the inbound :class:`PluginContext` so
    capabilities can read the canonical relationship a project has with
    an Integration without re-querying the graph.  Each connection
    mirrors one ``(:Project)-[:EXISTS_IN]->(:Integration)`` edge.

    Capabilities only ever *read* these; the canonical relationship is
    maintained through :class:`ServiceWriteback`.
    """

    #: Slug of the ``Integration`` the project exists in.
    integration_slug: str
    #: Opaque, stable identifier the remote uses for the project (e.g.
    #: a GitHub repository id or a SonarQube project key).
    identifier: str
    #: Canonical API URL (returns JSON) for the project in the remote.
    #: ``None`` when the edge predates canonical-URL maintenance.
    canonical_url: str | None = None


class ServiceWriteback(pydantic.BaseModel):
    """A project's Integration relationship the host should persist.

    Set by a lifecycle capability on :class:`PluginContext` when a call
    created, moved, or tore down the project's relationship with the
    Integration the capability is bound to.  The host persists it as the
    ``(:Project)-[:EXISTS_IN]->(:Integration)`` edge -- writing
    ``identifier`` and the canonical API URL -- and merges any
    ``dashboard_links`` into ``Project.links``.

    The host owns the capability-to-Integration binding: the writeback
    targets the Integration the capability is attached to (surfaced as
    :attr:`PluginContext.integration_slug`), so it carries no slug of its
    own and a capability cannot write an edge to an arbitrary Integration.

    Capabilities only ever *write* this field; it is ``None`` on every
    inbound context.
    """

    #: Opaque, stable identifier for the project in the remote (e.g. a
    #: GitHub repository id).  Stored on the ``EXISTS_IN`` edge.
    identifier: str
    #: Canonical API URL (returns JSON) for the project in the remote.
    #: Stored on the ``EXISTS_IN`` edge.  For id-based URLs (e.g. GitHub
    #: ``/repositories/{id}``) this is rename-stable.
    canonical_url: str
    #: Human-facing dashboard URLs to merge into ``Project.links``,
    #: keyed by the ``Project.links`` key (typically the Integration slug).
    dashboard_links: dict[str, str] = {}
    #: Optional encrypted secret to store on the ``EXISTS_IN`` edge
    #: alongside ``identifier`` -- e.g. a per-subscription webhook signing
    #: secret a gateway later reads to verify inbound deliveries.  The
    #: capability is responsible for encrypting it (the host persists the
    #: value verbatim and never decrypts it); ``None`` leaves any existing
    #: edge secret untouched.
    webhook_secret_enc: str | None = None
    #: When ``True`` the host removes the ``EXISTS_IN`` edge and the
    #: ``dashboard_links`` keys instead of upserting them -- e.g. on
    #: project delete or relocation away from this Integration.
    remove: bool = False


class PluginContext(pydantic.BaseModel):
    project_id: str
    project_slug: str
    org_slug: str
    team_slug: str | None = None
    environment: str | None = None
    assignment_options: dict[str, typing.Any] = {}
    # The Integration's resolved integration-level option values (e.g.
    # github host/flavor, aws region). Populated by the host so a
    # capability can read connection-level config without re-declaring it.
    integration_options: dict[str, typing.Any] = {}
    # The invoked capability's own option values (from
    # ``Integration.capabilities[kind].options``, layered with any
    # ``USES``-edge overrides). Empty when the capability declares none.
    capability_options: dict[str, typing.Any] = {}
    # Project's external links (e.g. ``{"github-repository": "https://..."}``).
    # Populated by the host so capabilities can derive per-project state
    # (e.g. the GitHub owner/repo) from the link map instead of
    # duplicating it as options on every assignment.
    project_links: dict[str, str] = {}
    # Slugs of every ``ProjectType`` the project is tagged with.
    # Capabilities may use these as a discovery hint (e.g. trying each as
    # a candidate GitHub owner) when an explicit link or option isn't
    # supplied.
    project_type_slugs: list[str] = []
    # Per-environment payload resolved by the host from the ``USES``
    # edge's ``env_payloads`` map (project edge layered over project-type
    # edge, mirroring how ``assignment_options`` is merged).  Empty when
    # no per-env payload is configured for ``environment``.  Capabilities
    # typically merge this into workflow inputs at trigger time; absent
    # keys should fall back to defaults rather than raise.
    environment_config: dict[str, typing.Any] = {}
    actor_user_id: str | None = None
    identity: IdentityCredentials | None = None
    # Project slug as it stood *before* the in-flight update.  Populated
    # by the host on ``on_project_updated`` / ``on_project_relocated``
    # so capabilities can locate the remote when the stored link is stale
    # or absent and only the slug just changed.  ``None`` for all other
    # events; ``project_slug`` continues to carry the current slug.
    previous_project_slug: str | None = None
    # Project-type slugs as they stood *before* the in-flight update.
    # Populated by the host on ``on_project_relocated`` (and optionally
    # on ``on_project_updated``) so capabilities comparing prior vs
    # current type-driven targets can decide what to do.  Empty list for
    # events where the host has no prior snapshot.
    previous_project_type_slugs: list[str] = []
    # Team slug as it stood *before* an in-flight ``on_project_relocated``
    # (i.e. before the team-assignment change).  ``None`` for all other
    # events; ``team_slug`` continues to carry the current team.  Lets
    # team-keyed lifecycle capabilities map the old team to its old
    # routing target and the new team to the new one (e.g. PagerDuty
    # escalation policy).
    previous_team_slug: str | None = None
    # Project display name, populated by the host on create / update
    # events.  Capabilities use this for human-facing artifacts (e.g. PR
    # bodies); GitHub repos do not expose a separate display-name field,
    # so it is intentionally not synced to the repo by the bundled GitHub
    # plugin.
    project_name: str | None = None
    # Project description, populated by the host on create / update
    # events.  Capabilities write it through to the remote's description
    # field (e.g. GitHub repo ``description``).
    project_description: str | None = None
    # Canonical Imbi UI deep link for the project (built from the
    # configured public UI base URL + project route).  Populated by the
    # host on create / update events; capabilities write it through to the
    # remote's homepage-style field (e.g. GitHub repo ``homepage``).
    project_ui_url: str | None = None
    # Output side-channel: a deployment / lifecycle capability sets this
    # when the project's stored link should be rewritten -- e.g. after
    # creating a new repo, after a rename that returned a 301, or after
    # a transfer to a new owner.  The host reads it after the call and
    # self-heals the stored link.  ``None`` on every inbound context.
    link_writeback: LinkWriteback | None = None
    # Output side-channel: a lifecycle capability sets this when the
    # project's relationship with the Integration it is bound to should be
    # created, updated, or torn down.  The host persists it as the
    # ``EXISTS_IN`` edge (identifier + canonical API URL) against
    # ``integration_slug`` and merges any dashboard links into
    # ``Project.links``.  ``None`` on every inbound context.
    service_writeback: ServiceWriteback | None = None
    # Slug of the ``Integration`` the running capability is bound to,
    # resolved by the host.  Tells the capability which Integration its
    # ``service_writeback`` targets and which ``service_connections``
    # entry is its own.  ``None`` for capabilities not bound to an
    # Integration.
    integration_slug: str | None = None
    # The project's ``EXISTS_IN`` connections, populated by the host so
    # capabilities (e.g. an analysis "doctor") can read the canonical
    # relationship without re-querying the graph.  Empty when the project
    # exists in no Integrations.
    service_connections: list[ServiceConnection] = []
    # Host-injected resolver mapping an external identity *subject* (e.g.
    # a GitHub numeric user id) to the matching Imbi user's email, or
    # ``None`` when no active ``IdentityConnection`` matches.  Lets a
    # capability attribute external actors (e.g. commit authors) to Imbi
    # users without knowing how the host reaches the identity store --
    # the gateway wires an HTTP ``/users/by-identity`` lookup, the
    # imbi-api worker a direct graph query.  ``None`` when the host wires
    # no resolver.  It is a live callable, not data, so it is excluded
    # from serialization and never set on a deserialized context.
    resolve_user_by_identity: typing.Annotated[
        collections.abc.Callable[[str], collections.abc.Awaitable[str | None]]
        | None,
        pydantic.Field(default=None, exclude=True, repr=False),
    ] = None


class ConfigValue(pydantic.BaseModel):
    data_type: str
    value: str
    secret: bool = False


class ConfigKey(pydantic.BaseModel):
    key: str
    data_type: str
    last_modified: datetime.datetime | None = None
    secret: bool = False


class ConfigKeyWithValue(ConfigKey):
    value: str


class LogFilter(pydantic.BaseModel):
    field: str
    op: typing.Literal['eq', 'ne', 'contains', 'starts_with', 'regex']
    value: str


class LogQuery(pydantic.BaseModel):
    start_time: datetime.datetime
    end_time: datetime.datetime
    filters: list[LogFilter] = []
    limit: int = 100
    cursor: str | None = None
    # Canonical level names to include (e.g. ['ERROR', 'WARN']). Empty
    # list means no level filter — return all levels. Capabilities
    # translate this into the underlying log source's level field at
    # query time so matching events can be returned even when the
    # requested levels are rare in the time window.
    levels: list[str] = []


class LogEntry(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    timestamp: datetime.datetime
    message: str
    level: str | None = None
    raw: dict[str, typing.Any] = {}


class LogHistogramBucket(pydantic.BaseModel):
    """A single time bucket in a log histogram response."""

    timestamp: datetime.datetime
    count: int
    levels: dict[str, int] = {}


class LogResult(pydantic.BaseModel):
    entries: list[LogEntry]
    next_cursor: str | None = None
    total: int | None = None
    warnings: list[str] = []


class IncidentView(pydantic.BaseModel):
    """A single incident row in an :class:`IncidentResult`."""

    id: str
    title: str
    status: str
    # ``None`` because some incident payloads omit urgency (e.g.
    # maintenance-window or low-signal sources); callers should not
    # assume it is always present.
    urgency: str | None = None
    created_at: datetime.datetime
    resolved_at: datetime.datetime | None = None
    url: str
    service: str | None = None


class IncidentResult(pydantic.BaseModel):
    incidents: list[IncidentView] = []
    next_cursor: str | None = None
    # ``None`` when the source does not report a total without a full
    # scan (live-query sources typically cannot).
    total: int | None = None


# ---------------------------------------------------------------------------
# Deployment data models
# ---------------------------------------------------------------------------


class Ref(pydantic.BaseModel):
    """A branch, tag, or default-ref pointer on a deployable repo."""

    name: str
    kind: typing.Literal['branch', 'tag', 'default']
    sha: str
    is_default: bool = False
    ahead: int | None = None
    behind: int | None = None
    pr_number: int | None = None
    pr_title: str | None = None
    pr_state: typing.Literal['open', 'closed', 'merged'] | None = None


CheckStatus = typing.Literal['pass', 'fail', 'warn', 'unknown']


class Commit(pydantic.BaseModel):
    """A commit on a deployable repo, hydrated for UI display."""

    sha: str
    short_sha: str
    message: str
    author: str | None = None
    authored_at: datetime.datetime | None = None
    url: str | None = None
    ci_status: CheckStatus = 'unknown'
    pr_number: int | None = None
    is_head: bool = False


class CompareResult(pydantic.BaseModel):
    """Result of comparing two commit-ish refs (``base..head``)."""

    base_sha: str
    head_sha: str
    ahead: int
    behind: int
    commits: list[Commit] = []
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    pr_numbers: list[int] = []


class RefInfo(pydantic.BaseModel):
    """Metadata returned after creating a ref (e.g. an annotated tag)."""

    name: str
    sha: str
    url: str | None = None


class ReleaseInfo(pydantic.BaseModel):
    """Metadata returned after creating a release on the remote."""

    id: str
    tag: str
    name: str | None = None
    url: str | None = None
    html_url: str | None = None
    prerelease: bool = False


class WorkflowFile(pydantic.BaseModel):
    """A CI workflow file discoverable in the project's remote repo.

    Returned by :meth:`DeploymentCapability.list_workflows` so the UI can
    populate a workflow dropdown when an operator wires up the
    per-environment dispatch edge.  ``id`` is the remote's stable
    identifier (e.g. the GitHub workflow id); ``path`` is the repo-
    relative file path; ``name`` is the human label from the workflow
    file's ``name:`` field.
    """

    id: str
    path: str
    name: str
    state: str = 'active'


class DeploymentRun(pydantic.BaseModel):
    """A workflow / pipeline run triggered by ``trigger_deployment``."""

    run_id: str
    run_url: str | None = None
    status: typing.Literal[
        'queued',
        'in_progress',
        'success',
        'failure',
        'cancelled',
        'unknown',
    ] = 'queued'
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None


#: Status values used on persisted ``DeploymentEvent`` rows.  This is
#: the host's canonical vocabulary -- capabilities normalize their
#: remote's native states to one of these before returning a
#: :class:`RemoteDeployment`.
DeploymentEventStatus = typing.Literal[
    'pending', 'in_progress', 'success', 'failed', 'rolled_back'
]


class RemoteDeployment(pydantic.BaseModel):
    """A deployment observed on the remote for resync.

    Returned by :meth:`DeploymentCapability.list_recent_deployments` so
    the host can backfill ``Release`` nodes and ``DEPLOYED_TO`` edges when
    webhook delivery has lapsed or when bringing a project online for
    the first time.  ``environment`` is the remote's environment name as
    reported (callers map it to the project's local environment slug).
    ``sha`` is the commit the deployment was created against;
    ``ref`` is the human-facing label the deploy was triggered with
    (branch / tag / SHA prefix) and may be ``None`` for older deploys.
    ``external_run_id`` MUST be a stable identifier (e.g. the GitHub
    deployment id) so the host can dedupe re-runs of resync without
    appending duplicate events.
    """

    environment: str
    sha: str
    ref: str | None = None
    status: DeploymentEventStatus
    created_at: datetime.datetime
    external_run_id: str
    run_url: str | None = None
    deployment_url: str | None = None
    description: str | None = None
    #: Identifier (typically a username/login) of whoever originated the
    #: deployment on the remote. ``None`` when the remote doesn't expose
    #: the creator or the capability can't determine one.
    creator: str | None = None
    #: The remote provider's stable unique id for the creator (the
    #: identity *subject* — e.g. the numeric GitHub user id as a string),
    #: used to resolve the deployer to an Imbi user via identity
    #: attribution. ``None`` when the remote doesn't expose it.
    creator_subject: str | None = None


# ---------------------------------------------------------------------------
# Lifecycle data models
# ---------------------------------------------------------------------------


class LifecycleResult(pydantic.BaseModel):
    """Outcome of a lifecycle capability invocation.

    Returned by :class:`LifecycleCapability` hooks so the host can record
    per-capability status alongside the entity state change and surface
    it to the operator without rolling back the Imbi-side write.
    """

    status: typing.Literal['ok', 'skipped', 'failed']
    message: str | None = None
    artifacts: dict[str, str] = {}


class RelocationTarget(pydantic.BaseModel):
    """Where a lifecycle capability would route a project's external link.

    Returned by :meth:`LifecycleCapability.resolve_relocation_target` so
    the host can answer "would changing this project's types move its
    repository?" without inlining plugin-specific resolution (e.g.
    GitHub org mapping, GitLab namespace) into the API layer.

    The host treats ``identifier`` as opaque -- it compares two
    :class:`RelocationTarget` instances by ``link_key`` + ``identifier``
    and surfaces ``display`` to the operator for confirmation.
    Capabilities typically use ``"<owner>/<repo>"`` or an equivalent
    stable handle for ``identifier`` and the same string for ``display``
    unless a nicer label is available.
    """

    #: Which ``PluginContext.project_links`` key this target governs.
    link_key: str
    #: Stable identifier the host compares for equality (e.g.
    #: ``"aweber-imbi/my-project"``).
    identifier: str
    #: Operator-facing label for confirmation dialogs.  Defaults to
    #: ``identifier`` when ``None``.
    display: str | None = None


# ---------------------------------------------------------------------------
# Webhook action data models
# ---------------------------------------------------------------------------


#: Action callable contract. Webhook action implementations are
#: ``async`` functions invoked by the host with a uniform keyword-only
#: signature: ``ctx`` (standard :class:`PluginContext`),
#: ``credentials`` (decrypted Integration credential blob, ``{}`` when
#: the plugin declares none), ``external_identifier`` (the value resolved
#: by the gateway from ``IMPLEMENTED_BY.identifier_selector`` --
#: pass-through as an empty string when not in play), ``action_config``
#: (a **pre-validated** instance of the action's
#: :attr:`ActionDescriptor.config_model`, never a raw JSON string), and
#: ``event`` (the event context).
#:
#: ``event`` mirrors the project-independent fields of the
#: :class:`~imbi_common.models.Event` row the host records for the
#: delivery, so an action reads the same data a ``WebhookRule`` filter
#: matches on:
#:
#: - ``type`` -- resolved event type (e.g. a GitHub ``X-GitHub-Event``)
#: - ``integration`` -- Integration slug
#: - ``attributed_to`` -- resolved Imbi user (``''`` when unattributed)
#: - ``metadata.headers`` -- request headers, keys lower-cased and
#:   sensitive values redacted
#: - ``payload`` -- the raw webhook body
#:
#: ``config_model`` JSON-Pointer selectors therefore resolve against the
#: event (the body lives under ``/payload``), and CEL expressions read
#: ``payload.<field>`` (plus ``type`` / ``metadata`` / etc.).
WebhookActionCallable = collections.abc.Callable[
    ...,
    collections.abc.Awaitable[None],
]


class ActionDescriptor(pydantic.BaseModel):
    """Describes a single action exposed by a webhook-actions capability.

    A :class:`WebhookActionsCapability` returns a list of these from
    :meth:`~WebhookActionsCapability.actions` so the host can:

    1. Look the action up by ``name`` after parsing ``WebhookRule.handler``
       as ``"<plugin_slug>#<action_name>"``.
    2. Resolve :attr:`callable` lazily via ``pydantic.ImportString`` and
       invoke it with the uniform :data:`WebhookActionCallable` signature.
    3. Resolve :attr:`config_model` to validate the rule's
       ``handler_config`` JSON blob *before* dispatching, and to surface
       :meth:`pydantic.BaseModel.model_json_schema` to the rule editor UI.

    ``label`` and ``description`` are operator-facing text. The UI pairs
    them with the JSON Schema derived from ``config_model`` to render
    the rule editor; no additional per-field metadata is needed on the
    descriptor itself because pydantic ``Field(...)`` annotations on
    the config model fields already flow through to the schema.
    """

    name: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9_]*$',
        min_length=1,
        description=(
            'Stable action key used in WebhookRule.handler after the '
            "'#' separator. Must be unique within a single plugin."
        ),
    )
    label: str = pydantic.Field(
        min_length=1,
        description='Short operator-facing title shown in the rule editor.',
    )
    description: str | None = pydantic.Field(
        default=None,
        description='Optional operator-facing help text.',
    )
    callable: pydantic.ImportString[WebhookActionCallable]
    config_model: pydantic.ImportString[type[pydantic.BaseModel]]


class ToolDescriptor(pydantic.BaseModel):
    """Describes a single agent-consumable tool. **PROVISIONAL.**

    Reserved for the ``tools`` capability kind so agents (imbi-assistant /
    imbi-mcp) can enumerate a plugin's tools without a future base-model
    change. The shape is intentionally minimal and **provisional** — it
    will be finalized with the agents work; do not build against it yet.
    """

    name: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9_]*$',
        min_length=1,
        description='Stable tool name; unique within a single plugin.',
    )
    description: str = pydantic.Field(min_length=1)
    #: JSON Schema for the tool's input arguments.
    input_schema: dict[str, typing.Any] = {}
    callable: pydantic.ImportString[collections.abc.Callable[..., typing.Any]]


# ---------------------------------------------------------------------------
# Capability handler contracts
# ---------------------------------------------------------------------------


class CapabilityHandler(abc.ABC):  # noqa: B024 - intentional marker base
    """Base for all capability implementations.

    Stateless; a new instance is created per request. Every method
    receives ``(ctx: PluginContext, credentials: dict[str, str], ...)``
    where ``credentials`` is the Integration's decrypted blob — always
    the same blob for every capability of the Integration.
    """


class ConfigurationCapability(CapabilityHandler):
    @abc.abstractmethod
    async def list_keys(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[ConfigKey]: ...

    @abc.abstractmethod
    async def get_values(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        keys: list[str] | None = None,
    ) -> list[ConfigKeyWithValue]: ...

    @abc.abstractmethod
    async def set_value(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
        value: ConfigValue,
    ) -> ConfigKey: ...

    @abc.abstractmethod
    async def delete_key(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
    ) -> None: ...


class LogsCapability(CapabilityHandler):
    @abc.abstractmethod
    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult: ...

    @abc.abstractmethod
    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict[str, typing.Any]]: ...

    async def histogram(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
        bucket_count: int = 60,
    ) -> list[LogHistogramBucket]:
        """Return time-bucketed event counts for the histogram view.

        Capabilities that support histograms should override this method
        and set the ``supports_histogram`` hint.  The default returns an
        empty list, which causes the API to signal that histograms are
        unavailable for this source.
        """
        return []


class IdentityCapability(CapabilityHandler):
    """Authenticate a specific user to a remote via OIDC, OAuth 2.0, or
    an OIDC-shaped device-code flow (e.g. AWS IAM Identity Center)."""

    @abc.abstractmethod
    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest: ...

    @abc.abstractmethod
    async def exchange_code(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[IdentityProfile, IdentityCredentials]: ...

    @abc.abstractmethod
    async def refresh(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> IdentityCredentials: ...

    async def revoke(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        token: str,
    ) -> None:
        """Best-effort revocation. Default no-op for IdPs without revoke."""
        return None

    async def materialize(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        connection: IdentityCredentials,
        *,
        db: typing.Any | None = None,
        identity_options: dict[str, typing.Any] | None = None,
    ) -> IdentityCredentials:
        """Exchange the IdP token for a backend-specific credential.

        Default: return ``connection`` unchanged.  AWS IAM IC overrides
        this to call ``GetRoleCredentials`` and return STS keys in
        ``IdentityCredentials.extra``.

        ``db`` is the host's :class:`graph.Graph` (typed loosely to keep
        this base module independent of the graph package).
        ``identity_options`` is the identity capability's own resolved
        option values.
        """
        return connection


class DeploymentCapability(CapabilityHandler):
    """Act on a repo: enumerate refs/commits, compare them, create
    tags/releases, and trigger CI workflow runs."""

    @abc.abstractmethod
    async def list_refs(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        kind: typing.Literal['default', 'branch', 'tag', 'all'] = 'all',
        query: str | None = None,
    ) -> list[Ref]: ...

    @abc.abstractmethod
    async def list_commits(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref: str,
        limit: int = 25,
    ) -> list[Commit]: ...

    @abc.abstractmethod
    async def resolve_committish(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        committish: str,
    ) -> Commit: ...

    @abc.abstractmethod
    async def compare(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        base: str,
        head: str,
    ) -> CompareResult: ...

    @abc.abstractmethod
    async def trigger_deployment(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref_or_sha: str,
        inputs: dict[str, str] | None = None,
    ) -> DeploymentRun: ...

    @abc.abstractmethod
    async def get_deployment_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        run_id: str,
    ) -> DeploymentRun: ...

    async def get_check_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        committish: str,
    ) -> CheckStatus:
        """Aggregate CI check-runs status for a ref / SHA / tag.

        Optional — used by the release-train read path to surface a
        green/red dot per env's currently-deployed version.  Capabilities
        without a CI concept return ``'unknown'`` (the default).
        """
        del ctx, credentials, committish
        return 'unknown'

    async def create_tag(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        sha: str,
        tag: str,
        message: str,
    ) -> RefInfo:
        """Create an annotated tag on the remote.

        Optional — only required for the Promote flow.  Capabilities that
        cannot mint tags raise :class:`NotImplementedError`; the host
        surfaces the error to the caller.
        """
        raise NotImplementedError

    async def create_release(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        tag: str,
        name: str,
        body_markdown: str,
        prerelease: bool = False,
    ) -> ReleaseInfo:
        """Create a release on the remote (e.g. a GitHub Release).

        Optional — paired with :meth:`create_tag`.  Capabilities without a
        release concept raise :class:`NotImplementedError`.
        """
        raise NotImplementedError

    async def list_workflows(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[WorkflowFile]:
        """List CI workflow files defined in the project's remote repo.

        Optional — used by the UI to populate a workflow dropdown when an
        operator configures assignment ``env_payloads``.  Capabilities
        without a workflow concept raise :class:`NotImplementedError`.
        """
        del ctx, credentials
        raise NotImplementedError

    async def list_recent_deployments(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        environments: list[str],
        limit: int = 1,
    ) -> list[RemoteDeployment]:
        """Return the most recent ``limit`` deployments per environment.

        Optional -- powers the deployment resync flow that backfills
        ``Release`` nodes and ``DEPLOYED_TO`` edges when webhook delivery
        has lapsed.  Capabilities that advertise the
        ``supports_deployment_sync`` hint MUST implement this; others
        raise :class:`NotImplementedError` (the host treats that as
        "skip resync").

        ``environments`` is the remote-facing list of environment names
        the host wants populated, in the project's preferred order.
        Capabilities should ignore environments their remote does not know
        about (rather than raising) so a partial resync still succeeds.
        Returned events MUST carry a stable ``external_run_id`` so the
        host can dedupe.
        """
        del ctx, credentials, environments, limit
        raise NotImplementedError


class LifecycleCapability(CapabilityHandler):
    """React to project state changes -- create, update, archive,
    unarchive, delete, relocate -- by mirroring the change to a backing
    remote (e.g. creating, renaming, transferring, or deleting a GitHub
    repository).  The host invokes the hooks *after* the authoritative
    Imbi state change has succeeded so a third-party failure does not
    roll back the operator's intent; failures are captured on
    :class:`LifecycleResult` and surfaced without aborting the write.

    Only :meth:`on_project_archived` is required.  The remaining hooks
    default to raising :class:`NotImplementedError`, which the host
    dispatcher maps to ``LifecycleResult(status='skipped')``.
    Capabilities advertise the events they actually handle via the
    ``lifecycle_events`` hint so the UI can gate the matching affordances.
    """

    @abc.abstractmethod
    async def on_project_archived(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult: ...

    async def on_project_unarchived(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being unarchived. Optional."""
        del ctx, credentials
        raise NotImplementedError

    async def on_project_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being created in Imbi. Optional -- typical
        capabilities provision the backing remote and set
        ``ctx.link_writeback``."""
        del ctx, credentials
        raise NotImplementedError

    async def on_project_updated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a sync-relevant project field changing. Optional --
        ``ctx.previous_project_slug`` carries the prior slug for locating
        the remote when the stored link is stale."""
        del ctx, credentials
        raise NotImplementedError

    async def on_project_deleted(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being deleted in Imbi. Optional -- invoked
        *after* the project node has been removed, with a context bundle
        captured *before* ``DETACH DELETE``.  ``404`` should be treated
        as ``LifecycleResult(status='skipped')``."""
        del ctx, credentials
        raise NotImplementedError

    async def on_project_relocated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being routed to a different remote target.
        Optional -- ``ctx.project_type_slugs`` is the post-change set;
        ``ctx.previous_project_type_slugs`` is the pre-change set."""
        del ctx, credentials
        raise NotImplementedError

    async def resolve_relocation_target(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> RelocationTarget | None:
        """Resolve the remote target this capability would route ``ctx``
        to.  Optional -- returning ``None`` (the default) signals no
        relocate concept.  Implementations resolve deterministically from
        ``ctx`` and MUST NOT call out to the remote."""
        del ctx, credentials
        return None


class WebhookActionsCapability(CapabilityHandler):
    """Declares a static catalog of gateway-dispatched actions.

    The host (``imbi-gateway``) parses ``WebhookRule.handler`` as
    ``"<plugin_slug>#<action_name>"``, looks the plugin up in the
    registry, picks the matching :class:`ActionDescriptor`, validates the
    rule's ``handler_config`` against
    :attr:`ActionDescriptor.config_model`, and calls
    :attr:`ActionDescriptor.callable` with the uniform signature captured
    in :data:`WebhookActionCallable`. The capability itself carries no
    runtime dispatch logic — the callable lives wherever the descriptor
    points.
    """

    @classmethod
    @abc.abstractmethod
    def actions(cls) -> list[ActionDescriptor]:
        """Return the static catalog of actions this capability exposes.

        Implementations should return a fresh list each call so callers
        can mutate the result safely. The host validates each descriptor's
        ``callable`` and ``config_model`` ImportStrings at registry load,
        so misconfigured paths fail loud there rather than at request time.
        """


# ---------------------------------------------------------------------------
# Analysis data models
# ---------------------------------------------------------------------------


#: Possible statuses for a single ``AnalysisResultItem``. ``fail`` is
#: the worst, ``warn`` is intermediate, ``pass`` is healthy — the
#: Doctor panel groups results in that order and the report's
#: ``overall_status`` is the worst observed across all items.
AnalysisResultStatus = typing.Literal['pass', 'warn', 'fail']


class RemediationOffer(pydantic.BaseModel):
    """An offer to fix the finding it is attached to.

    A finding is *fixable* iff it carries a ``RemediationOffer``.  The
    Doctor panel renders a button labelled ``label``; clicking it asks
    the host to call the emitting capability's
    :meth:`AnalysisCapability.remediate` with this offer's ``id``.  The
    ``id`` is opaque and plugin-defined (it only has to be unique within
    the capability's own findings) — it round-trips back unchanged so the
    capability knows which fix to perform.
    """

    id: str
    label: str
    #: Optional confirmation prompt shown before the fix runs.
    confirm: str | None = None
    #: When ``True`` the UI requires explicit confirmation — set it for
    #: fixes that create/remove an edge or delete a value rather than
    #: simply reconciling Imbi state to an external source of truth.
    destructive: bool = False


class RemediationResult(pydantic.BaseModel):
    """Outcome of an :meth:`AnalysisCapability.remediate` call.

    ``status`` is ``fixed`` when the capability changed state, ``noop``
    when the finding was already resolved (so a double-click or a bulk
    "fix all" pass is safe), and ``failed`` when the fix could not be
    applied.  ``message`` is human-facing and rendered as Markdown.
    """

    status: typing.Literal['fixed', 'noop', 'failed']
    message: str


class AnalysisResultItem(pydantic.BaseModel):
    """A single finding emitted by an :class:`AnalysisCapability`.

    Stable per-capability ``slug`` lets scoring policies and the UI refer
    to a result across runs. ``description`` is rendered as Markdown by
    the Project Doctor panel.  When ``remediation`` is set the finding
    is fixable — see :class:`RemediationOffer`.
    """

    slug: str
    title: str
    description: str
    status: AnalysisResultStatus
    remediation: RemediationOffer | None = None


class AnalysisCapability(CapabilityHandler):
    """Inspect a project (via its links, Integration connections, and the
    Integration credentials) and return pass/warn/fail findings that
    surface in the Project Doctor panel and feed the ``analysis_result``
    scoring-policy category.

    A capability that attaches a :class:`RemediationOffer` to any finding
    must also override :meth:`remediate` to apply that fix.  Like every
    other capability method, ``remediate`` has no database handle: it
    effects graph changes by setting ``ctx.service_writeback`` /
    ``ctx.link_writeback``, which the host captures and persists.
    """

    @abc.abstractmethod
    async def analyze(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[AnalysisResultItem]: ...

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        """Apply the fix identified by ``remediation_id``.

        ``remediation_id`` is the ``id`` of a :class:`RemediationOffer`
        this capability previously emitted on a finding.  Implementations
        should re-verify the discrepancy against fresh state and return a
        ``noop`` :class:`RemediationResult` when it is already resolved,
        so the call is idempotent.

        Report the outcome by **returning** a :class:`RemediationResult`:
        ``fixed`` when state changed, ``noop`` when already resolved, and
        ``failed`` (with a user-facing ``message``) when the fix could not
        be applied.  Implementations should catch their own errors and
        translate them rather than letting exceptions escape.

        The default raises :class:`PluginRemediationNotSupported`; only
        capabilities that emit remediation offers need override it.
        """
        raise PluginRemediationNotSupported(
            type(self).__name__, remediation_id
        )


class IncidentsCapability(CapabilityHandler):
    """Live-query a remote incident-management system (e.g. PagerDuty) for
    the incidents tied to a project's Integration and return them for the
    project-detail Incidents tab.  There is no local incident store; the
    source of record stays authoritative and the tab is read-only.
    """

    @abc.abstractmethod
    async def list_incidents(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        *,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        statuses: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> IncidentResult: ...


class CommitSyncCapability(CapabilityHandler):
    """Ingest a project's commit (and tag) history into ClickHouse.

    Addressed directly by the host (manual sync endpoints, availability
    checks) and independently permissioned (``project:commits:write``).
    The gateway-side webhook delivery for incremental sync still flows
    through the plugin's ``webhook-actions`` catalog; this kind exists so
    the host can resolve/enable/assign commit-sync on its own.
    """

    @abc.abstractmethod
    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> tuple[int, int]:
        """Record the project's full commit and tag history.

        Host-invoked (no webhook payload). Returns
        ``(commits_recorded, tags_recorded)``. Re-running is safe: the
        ClickHouse ``commits`` / ``tags`` tables are ``ReplacingMergeTree``
        and dedupe against rows the webhook already recorded.
        """

    async def check_available(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> bool:
        """Whether an on-demand sync can run for ``ctx`` right now.

        Default ``True``; override to report ``False`` when the remote /
        repository can't be resolved so the host can hide the affordance.
        """
        del ctx, credentials
        return True


class PullRequestSyncCapability(CapabilityHandler):
    """Ingest a project's pull-request history into ClickHouse.

    Addressed directly by the host (manual sync endpoints, availability
    checks) and independently permissioned
    (``project:pull-requests:write``). The gateway-side webhook delivery
    still flows through the plugin's ``webhook-actions`` catalog.
    """

    @abc.abstractmethod
    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> int:
        """Record the project's full pull-request history.

        Host-invoked (no webhook payload). Returns the number of PRs
        recorded. Re-running is safe: the ClickHouse ``pull_requests``
        table is ``ReplacingMergeTree``.
        """

    async def check_available(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> bool:
        """Whether an on-demand sync can run for ``ctx`` right now.

        Default ``True``; override to report ``False`` when the remote /
        repository can't be resolved.
        """
        del ctx, credentials
        return True


class ToolsCapability(CapabilityHandler):
    """Reserved. Returns tool descriptors for imbi-assistant / imbi-mcp.

    The contract will be finalized with the agents work; declaring it now
    reserves the kind and surface. **PROVISIONAL** — do not build against
    :class:`ToolDescriptor` yet.
    """

    @classmethod
    @abc.abstractmethod
    def tools(cls) -> list[ToolDescriptor]:
        """Return the static catalog of tools this capability exposes."""


#: One contract ABC per :data:`CapabilityKind`. The registry validates a
#: capability's ``handler`` against the entry for its kind.
CAPABILITY_CONTRACTS: dict[str, type[CapabilityHandler]] = {
    'configuration': ConfigurationCapability,
    'logs': LogsCapability,
    'identity': IdentityCapability,
    'deployment': DeploymentCapability,
    'lifecycle': LifecycleCapability,
    'webhook-actions': WebhookActionsCapability,
    'analysis': AnalysisCapability,
    'incidents': IncidentsCapability,
    'commit-sync': CommitSyncCapability,
    'pr-sync': PullRequestSyncCapability,
    'tools': ToolsCapability,
}


class Plugin(abc.ABC):
    """One per package. The :attr:`manifest` — including each capability's
    handler binding — is the complete declaration; the class itself holds
    no behavior and no separate capability map.
    """

    manifest: typing.ClassVar[PluginManifest]
