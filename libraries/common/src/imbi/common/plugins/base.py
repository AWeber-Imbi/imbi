"""Plugin base classes and shared data models."""

import abc
import collections.abc
import datetime
import typing

import pydantic


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
    deployment plugins, ``set_value`` / ``delete_key`` for config
    plugins).  The UI substitutes ``{{name}}`` placeholders against
    the payload merged with row-level fields (``version``,
    ``environment``, ``project``, ``performer``).
    """

    label: str
    summary: str | None = None


#: The category a plugin declares in its manifest. A plugin assignment
#: (the ``:USES_PLUGIN`` edge) is keyed by this value; the subset that
#: renders a project-detail tab (configuration, logs, lifecycle,
#: deployment) is a UI concern -- not every plugin type is a tab.
PluginType = typing.Literal[
    'configuration',
    'logs',
    'identity',
    'deployment',
    'lifecycle',
    'webhook',
    'analysis',
]


class PluginManifest(pydantic.BaseModel):
    slug: str
    name: str
    description: str | None = None
    plugin_type: PluginType
    auth_type: typing.Literal['api_token', 'oauth2', 'oidc', 'aws-iam-ic'] = (
        'api_token'
    )
    api_version: int = 1
    cacheable: bool = True
    supports_histogram: bool = False
    # Deployment plugins that can enumerate recent deployments from the
    # remote (see :meth:`DeploymentPlugin.list_recent_deployments`) set
    # this to ``True``.  The UI uses it to decide whether to show the
    # "Resync deployments" controls on project settings and admin TPS
    # pages; non-deployment plugins should leave it ``False``.
    supports_deployment_sync: bool = False
    login_capable: bool = False
    requires_identity: bool = False
    default_scopes: list[str] = []
    options: list[PluginOption] = []
    credentials: list[CredentialField] = []
    data_types: list[DataType] = []
    vertex_labels: list[PluginVertexLabel] = []
    edge_labels: list[PluginEdgeLabel] = []
    # Body copy shown on the dashboard "unconnected integration"
    # widget for identity plugins.  Plugin authors should write 1-3
    # short sentences explaining why the user benefits from
    # connecting their account (e.g. "Imbi can act as you on GitHub
    # instead of a shared service principal -- once you link your
    # account, pull requests, branch reads, and audit attribution all
    # run as @you.").  When ``None`` the widget falls back to the
    # plugin's ``description``.
    widget_text: str | None = None
    # Mustache-style templates the UI uses to render operations-log
    # entries tagged with this plugin's slug.  Keyed by the ``action``
    # value the API writes into the description JSON.  The empty-string
    # key acts as a fallback when no action is present.
    ops_log_templates: dict[str, OpsLogTemplate] = {}
    # Which project lifecycle events the plugin advertises support for.
    # The host reads this to decide whether to expose UI affordances
    # gated on a given event (e.g. "Also delete the repository" on
    # project delete, "Also move the repository" on a project-type
    # change that would route to a different target).  An unimplemented
    # hook still resolves to ``LifecycleResult(status='skipped')`` via
    # ``NotImplementedError``; this list is purely a capability hint.
    # Default preserves the pre-2.8 behavior where lifecycle plugins
    # only handled archive / unarchive.
    lifecycle_events: list[
        typing.Literal[
            'created',
            'updated',
            'archived',
            'unarchived',
            'deleted',
            'relocated',
        ]
    ] = ['archived', 'unarchived']


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
    """Materialized credentials handed to other plugins.

    Plugins receive this in :class:`PluginContext.identity` when the
    assignment declares an ``identity_plugin_id``.  The shape is close to
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

    Returned by identity plugins whose authorization flow is not a
    redirect (e.g. AWS IAM Identity Center device authorization).  The
    UI polls ``/me/identities/{plugin_id}/poll`` every ``interval``
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
    # Credentials the plugin minted on the fly during this call (e.g. an
    # OIDC dynamic-client registration for AWS IAM IC).  The host
    # persists them to the plugin's encrypted credential blob so that
    # the matching ``exchange_code`` / ``refresh`` calls -- which receive
    # ``credentials`` from storage, not from this object — see the same
    # client identity.  ``None`` means "nothing new to persist".
    registered_credentials: dict[str, str] | None = None


class LinkWriteback(pydantic.BaseModel):
    """A project-link URL the host should persist on the project node.

    Set by a deployment / lifecycle plugin on :class:`PluginContext` when
    the call mutated, created, or discovered the canonical URL for one
    of the project's external links.  Covers four cases:

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
    * **Discovery** -- the plugin resolved a link the host had not yet
      stored (e.g. by following a redirect chain).

    Plugins only ever *write* this field; it is not part of the
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


class ServicePlugin(pydantic.BaseModel):
    """A plugin connected to the same third-party service as the caller.

    Surfaced on :class:`PluginContext` so an action can introspect how
    its ``ThirdPartyService`` is configured -- e.g. a webhook action that
    needs the GitHub host/flavor reads it from the GitHub plugin attached
    to the same service rather than re-declaring it on the rule. Carries
    only the non-secret ``options`` map; credentials are never included.
    """

    slug: str
    options: dict[str, typing.Any] = {}


class ServiceConnection(pydantic.BaseModel):
    """A project's ``EXISTS_IN`` edge to a third-party service.

    Populated by the host on the inbound :class:`PluginContext` so
    plugins can read the canonical relationship a project has with a
    third-party service without re-querying the graph.  Each connection
    mirrors one ``(:Project)-[:EXISTS_IN]->(:ThirdPartyService)`` edge.

    Plugins only ever *read* these; the canonical relationship is
    maintained through :class:`ServiceWriteback`.
    """

    #: Slug of the ``ThirdPartyService`` the project exists in.
    service_slug: str
    #: Opaque, stable identifier the service uses for the project (e.g.
    #: a GitHub repository id or a SonarQube project key).
    identifier: str
    #: Canonical API URL (returns JSON) for the project in the service.
    #: ``None`` when the edge predates canonical-URL maintenance.
    canonical_url: str | None = None


class ServiceWriteback(pydantic.BaseModel):
    """A project's third-party-service relationship the host should persist.

    Set by a lifecycle plugin on :class:`PluginContext` when a call
    created, moved, or tore down the project's relationship with the
    service the plugin is bound to.  The host persists it as the
    ``(:Project)-[:EXISTS_IN]->(:ThirdPartyService)`` edge -- writing
    ``identifier`` and the canonical API URL -- and merges any
    ``dashboard_links`` into ``Project.links``.

    The host owns the plugin-to-service binding: the writeback targets
    the service the plugin is attached to (surfaced as
    :attr:`PluginContext.third_party_service_slug`), so it carries no
    service slug of its own and a plugin cannot write an edge to an
    arbitrary service.

    Plugins only ever *write* this field; it is ``None`` on every
    inbound context.
    """

    #: Opaque, stable identifier for the project in the service (e.g. a
    #: GitHub repository id).  Stored on the ``EXISTS_IN`` edge.
    identifier: str
    #: Canonical API URL (returns JSON) for the project in the service.
    #: Stored on the ``EXISTS_IN`` edge.  For id-based URLs (e.g. GitHub
    #: ``/repositories/{id}``) this is rename-stable.
    canonical_url: str
    #: Human-facing dashboard URLs to merge into ``Project.links``,
    #: keyed by the ``Project.links`` key (typically the service slug).
    dashboard_links: dict[str, str] = {}
    #: When ``True`` the host removes the ``EXISTS_IN`` edge and the
    #: ``dashboard_links`` keys instead of upserting them -- e.g. on
    #: project delete or relocation away from this service.
    remove: bool = False


class PluginContext(pydantic.BaseModel):
    project_id: str
    project_slug: str
    org_slug: str
    team_slug: str | None = None
    environment: str | None = None
    assignment_options: dict[str, typing.Any] = {}
    # Other plugins connected to the same ``ThirdPartyService`` as the
    # action being dispatched (slug + non-secret ``options``, never
    # credentials).  Populated by the host so an action can introspect
    # sibling configuration -- e.g. a webhook commit-sync action reading
    # the GitHub host/flavor off the GitHub plugin on the same service.
    # Empty when the host does not resolve a service or it has no plugins.
    service_plugins: list[ServicePlugin] = []
    # Project's external links (e.g. ``{"github-repository": "https://..."}``).
    # Populated by the host so plugins can derive per-project state (e.g. the
    # GitHub owner/repo) from the link map instead of duplicating it as
    # plugin options on every assignment.
    project_links: dict[str, str] = {}
    # Slugs of every ``ProjectType`` the project is tagged with. Plugins
    # may use these as a discovery hint (e.g. trying each as a candidate
    # GitHub owner) when an explicit link or option isn't supplied.
    project_type_slugs: list[str] = []
    # Per-environment payload resolved by the host from the
    # ``USES_PLUGIN`` edge's ``env_payloads`` map (project edge layered
    # over project-type edge, mirroring how ``assignment_options`` is
    # merged).  Empty when no per-env payload is configured for
    # ``environment``.  Plugins typically merge this into workflow
    # inputs at trigger time; absent keys should fall back to plugin
    # defaults rather than raise.
    environment_config: dict[str, typing.Any] = {}
    actor_user_id: str | None = None
    identity: IdentityCredentials | None = None
    # Project slug as it stood *before* the in-flight update.  Populated
    # by the host on ``on_project_updated`` / ``on_project_relocated``
    # so plugins can locate the remote when the stored link is stale or
    # absent and only the slug just changed.  ``None`` for all other
    # events; ``project_slug`` continues to carry the current slug.
    previous_project_slug: str | None = None
    # Project-type slugs as they stood *before* the in-flight update.
    # Populated by the host on ``on_project_relocated`` (and optionally
    # on ``on_project_updated``) so plugins comparing prior vs current
    # type-driven targets can decide what to do.  Empty list for events
    # where the host has no prior snapshot.
    previous_project_type_slugs: list[str] = []
    # Project display name, populated by the host on create / update
    # events.  Plugins use this for human-facing artifacts (e.g. PR
    # bodies); GitHub repos do not expose a separate display-name
    # field, so it is intentionally not synced to the repo by the
    # bundled GitHub plugin.
    project_name: str | None = None
    # Project description, populated by the host on create / update
    # events.  Plugins write it through to the remote's description
    # field (e.g. GitHub repo ``description``).
    project_description: str | None = None
    # Canonical Imbi UI deep link for the project (built from the
    # configured public UI base URL + project route).  Populated by the
    # host on create / update events; plugins write it through to the
    # remote's homepage-style field (e.g. GitHub repo ``homepage``).
    project_ui_url: str | None = None
    # Output side-channel: a deployment / lifecycle plugin sets this
    # when the project's stored link should be rewritten -- e.g. after
    # creating a new repo, after a rename that returned a 301, or after
    # a transfer to a new owner.  The host reads it after the call and
    # self-heals the stored link.  Plugins never read it -- it is
    # write-only from the plugin's perspective and ``None`` on every
    # inbound context.
    link_writeback: LinkWriteback | None = None
    # Output side-channel: a lifecycle plugin sets this when the
    # project's relationship with the service it is bound to should be
    # created, updated, or torn down.  The host persists it as the
    # ``EXISTS_IN`` edge (identifier + canonical API URL) against
    # ``third_party_service_slug`` and merges any dashboard links into
    # ``Project.links``.  Write-only from the plugin's perspective;
    # ``None`` on every inbound context.
    service_writeback: ServiceWriteback | None = None
    # Slug of the ``ThirdPartyService`` the running plugin is bound to,
    # resolved by the host from the
    # ``(:ThirdPartyService)-[:HAS_PLUGIN]->(:Plugin)`` edge.  Tells the
    # plugin which service its ``service_writeback`` targets and which
    # ``service_connections`` entry is its own.  ``None`` for plugins
    # not attached to a service.
    third_party_service_slug: str | None = None
    # The project's ``EXISTS_IN`` connections, populated by the host so
    # plugins (e.g. an analysis "doctor") can read the canonical
    # relationship without re-querying the graph.  Empty when the
    # project exists in no services.
    service_connections: list[ServiceConnection] = []
    # Host-injected resolver mapping an external identity *subject* (e.g.
    # a GitHub numeric user id) to the matching Imbi user's email, or
    # ``None`` when no active ``IdentityConnection`` matches.  Lets an
    # action attribute external actors (e.g. commit authors) to Imbi
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
    # list means no level filter — return all levels. Plugins translate
    # this into the underlying log source's level field at query time
    # so matching events can be returned even when the requested levels
    # are rare in the time window.
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


class ConfigurationPlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.
    """

    manifest: PluginManifest

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


class LogsPlugin(abc.ABC):
    manifest: PluginManifest

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

        Plugins that support histograms should override this method and
        set ``manifest.supports_histogram = True``.  The default
        implementation returns an empty list, which causes the API to
        signal that histograms are unavailable for this source.
        """
        return []


class IdentityPlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.  Identity plugins authenticate
    a specific user to a third-party system via OIDC, OAuth 2.0, or an
    OIDC-shaped device-code flow (e.g. AWS IAM Identity Center).
    """

    manifest: PluginManifest

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
        """Hook for plugins that need to exchange the IdP token for a
        backend-specific credential at call time.

        Default: return ``connection`` unchanged.  AWS IAM IC overrides
        this to call ``GetRoleCredentials`` and return STS keys in
        ``IdentityCredentials.extra``.

        ``db`` is the host's :class:`graph.Graph` (typed loosely to
        keep this base module independent of the graph package).
        Plugins that need to resolve per-environment configuration via
        ``MAPS_TO`` walks consult it.

        ``identity_options`` is the identity plugin instance's own
        ``Plugin.options`` dict, loaded by the host before the call.
        Distinct from ``credentials`` (which holds the plugin's
        OIDC/api-token configuration) and from
        ``ctx.assignment_options`` (which carries the *data* plugin's
        edge options at request time).
        """
        return connection


# ---------------------------------------------------------------------------
# Deployment plugin
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

    Returned by :meth:`DeploymentPlugin.list_workflows` so the UI can
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
#: the host's canonical vocabulary -- plugins normalize their remote's
#: native states to one of these before returning a
#: :class:`RemoteDeployment`.
DeploymentEventStatus = typing.Literal[
    'pending', 'in_progress', 'success', 'failed', 'rolled_back'
]


class RemoteDeployment(pydantic.BaseModel):
    """A deployment observed on the remote for resync.

    Returned by :meth:`DeploymentPlugin.list_recent_deployments` so the
    host can backfill ``Release`` nodes and ``DEPLOYED_TO`` edges when
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
    #: the creator or the plugin can't determine one.
    creator: str | None = None


class DeploymentPlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.  Deployment plugins act on a
    repo: enumerate refs/commits, compare them, create tags/releases,
    and trigger CI workflow runs.  They are typically paired with an
    :class:`IdentityPlugin` so deploy actions run as the human user
    rather than a shared service principal.
    """

    manifest: PluginManifest

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
        green/red dot per env's currently-deployed version.  Plugins
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

        Optional — only required for the Promote flow.  Plugins that
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

        Optional — paired with :meth:`create_tag`.  Plugins without a
        release concept raise :class:`NotImplementedError`.
        """
        raise NotImplementedError

    async def list_workflows(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[WorkflowFile]:
        """List CI workflow files defined in the project's remote repo.

        Optional — used by the UI to populate a workflow dropdown when
        an operator configures plugin assignment ``env_payloads``.
        Plugins without a workflow concept raise
        :class:`NotImplementedError`.
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
        ``Release`` nodes and ``DEPLOYED_TO`` edges when webhook
        delivery has lapsed.  Plugins that advertise
        ``supports_deployment_sync=True`` MUST implement this; others
        raise :class:`NotImplementedError` (the host treats that as
        "skip resync for this plugin").

        ``environments`` is the remote-facing list of environment names
        the host wants populated, in the project's preferred order.
        Plugins should ignore environments their remote does not know
        about (rather than raising) so a partial resync still succeeds.
        Returned events MUST carry a stable ``external_run_id`` so the
        host can dedupe.
        """
        del ctx, credentials, environments, limit
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Lifecycle plugin
# ---------------------------------------------------------------------------


class LifecycleResult(pydantic.BaseModel):
    """Outcome of a lifecycle plugin invocation.

    Returned by :class:`LifecyclePlugin` hooks so the host can record
    per-plugin status alongside the entity state change and surface it
    to the operator without rolling back the Imbi-side write.
    """

    status: typing.Literal['ok', 'skipped', 'failed']
    message: str | None = None
    artifacts: dict[str, str] = {}


class RelocationTarget(pydantic.BaseModel):
    """Where a lifecycle plugin would route a project's external link.

    Returned by :meth:`LifecyclePlugin.resolve_relocation_target` so the
    host can answer "would changing this project's types move its
    repository?" without inlining plugin-specific resolution (e.g.
    GitHub org mapping, GitLab namespace) into the API layer.

    The host treats ``identifier`` as opaque -- it compares two
    :class:`RelocationTarget` instances by ``link_key`` + ``identifier``
    and surfaces ``display`` to the operator for confirmation.  Plugins
    typically use ``"<owner>/<repo>"`` or an equivalent stable handle
    for ``identifier`` and the same string for ``display`` unless a
    nicer label is available.
    """

    #: Which ``PluginContext.project_links`` key this target governs.
    link_key: str
    #: Stable identifier the host compares for equality (e.g.
    #: ``"aweber-imbi/my-project"``).
    identifier: str
    #: Operator-facing label for confirmation dialogs.  Defaults to
    #: ``identifier`` when ``None``.
    display: str | None = None


class LifecyclePlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.  Lifecycle plugins react to
    project state changes -- create, update, archive, unarchive,
    delete, relocate -- by mirroring the change to a backing remote
    (e.g. creating, renaming, transferring, or deleting a GitHub
    repository).  The host invokes the hooks *after* the authoritative
    Imbi state change has succeeded so a third-party failure does not
    roll back the operator's intent; failures are captured on
    :class:`LifecycleResult` and surfaced without aborting the write.

    Only :meth:`on_project_archived` is required.  The remaining hooks
    default to raising :class:`NotImplementedError`, which the host
    dispatcher maps to ``LifecycleResult(status='skipped')``.  Plugins
    advertise the events they actually handle via
    :attr:`PluginManifest.lifecycle_events` so the UI can gate the
    matching affordances.
    """

    manifest: PluginManifest

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
        """React to a project being unarchived.

        Optional — plugins without a meaningful inverse return
        ``LifecycleResult(status='skipped')`` or raise
        :class:`NotImplementedError`.  The default raises so the host
        can surface an explicit warning rather than silently swallow.
        """
        del ctx, credentials
        raise NotImplementedError

    async def on_project_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being created in Imbi.

        Optional -- typical plugins provision the backing remote (e.g.
        ``POST /orgs/{org}/repos``) and set ``ctx.link_writeback`` so
        the host stores the canonical link on the project node.
        Plugins without a create concept raise
        :class:`NotImplementedError`; the host dispatcher maps that to
        ``LifecycleResult(status='skipped')``.
        """
        del ctx, credentials
        raise NotImplementedError

    async def on_project_updated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a sync-relevant project field changing in Imbi.

        Optional -- the host dispatches this when ``project_slug`` or
        ``project_description`` changes; ``ctx.previous_project_slug``
        carries the prior slug for locating the remote when the stored
        link is stale.  Typical plugins push name / description /
        homepage updates through to the remote and set
        ``ctx.link_writeback`` if the canonical URL changed.  Plugins
        without an update concept raise :class:`NotImplementedError`.
        """
        del ctx, credentials
        raise NotImplementedError

    async def on_project_deleted(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being deleted in Imbi.

        Optional -- the host invokes this *after* the project node has
        been removed, with a context bundle the host captured *before*
        ``DETACH DELETE`` (so ``project_links``, ``project_type_slugs``,
        etc. reflect the project as it existed).  Typical plugins
        delete the backing remote; ``404`` is treated as
        ``LifecycleResult(status='skipped')`` (already gone).  Plugins
        without a delete concept raise :class:`NotImplementedError`.
        """
        del ctx, credentials
        raise NotImplementedError

    async def on_project_relocated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        """React to a project being routed to a different remote target.

        Optional -- the host dispatches this only when the operator has
        explicitly opted in (e.g. via a "Also move the repository"
        checkbox on a project-type change).  ``ctx.project_type_slugs``
        is the post-change set; ``ctx.previous_project_type_slugs`` is
        the pre-change set.  Typical plugins transfer the remote
        (``POST /repos/{owner}/{repo}/transfer`` on GitHub), wait for
        the async settle, and set ``ctx.link_writeback`` to the new
        canonical URL.  Plugins without a relocate concept raise
        :class:`NotImplementedError`.
        """
        del ctx, credentials
        raise NotImplementedError

    async def resolve_relocation_target(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> RelocationTarget | None:
        """Resolve the remote target this plugin would route ``ctx`` to.

        Optional -- used by the host's lifecycle-preview endpoint to
        decide whether a project-type (or other) change would move the
        repository to a different remote.  Returning ``None`` (the
        default) signals the plugin has no relocate concept and the
        host should not surface a "move repository" affordance.

        Implementations resolve the target deterministically from
        ``ctx`` (typically ``project_type_slugs`` + plugin options) and
        MUST NOT call out to the remote -- the host may invoke this
        many times during a UI preview.
        """
        del ctx, credentials
        return None


# ---------------------------------------------------------------------------
# Webhook action plugin
# ---------------------------------------------------------------------------


#: Action callable contract. Webhook action implementations are
#: ``async`` functions invoked by the host with a uniform keyword-only
#: signature: ``ctx`` (standard :class:`PluginContext`),
#: ``credentials`` (decrypted credential blob, ``{}`` when the plugin
#: declares none), ``external_identifier`` (the value resolved by the
#: gateway from ``IMPLEMENTED_BY.identifier_selector`` -- pass-through
#: as an empty string when not in play), ``action_config`` (a
#: **pre-validated** instance of the action's
#: :attr:`ActionDescriptor.config_model`, never a raw JSON string), and
#: ``event`` (the event context).
#:
#: ``event`` mirrors the project-independent fields of the
#: :class:`~imbi_common.models.Event` row the host records for the
#: delivery, so an action reads the same data a ``WebhookRule`` filter
#: matches on:
#:
#: - ``type`` -- resolved event type (e.g. a GitHub ``X-GitHub-Event``)
#: - ``third_party_service`` -- service slug
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
    """Describes a single action exposed by a :class:`WebhookActionPlugin`.

    Plugins return a list of these from :meth:`WebhookActionPlugin.actions`
    so the host can:

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


class WebhookActionPlugin(abc.ABC):
    """Base class for webhook-action plugins.

    Webhook action plugins declare a manifest (slug, credentials,
    optional configuration options) so operators can install and
    configure them like any other plugin, and advertise a static
    catalog of actions through :meth:`actions`. The host
    (``imbi-gateway``) parses ``WebhookRule.handler`` as
    ``"<plugin_slug>#<action_name>"``, looks the plugin up in the
    registry, picks the matching :class:`ActionDescriptor`, validates
    the rule's ``handler_config`` against
    :attr:`ActionDescriptor.config_model`, and calls
    :attr:`ActionDescriptor.callable` with the uniform signature
    captured in :data:`WebhookActionCallable`.

    The plugin class itself carries no runtime dispatch logic -- the
    callable lives wherever the descriptor points (typically the
    plugin's own ``actions`` submodule).
    """

    manifest: PluginManifest

    @classmethod
    @abc.abstractmethod
    def actions(cls) -> list[ActionDescriptor]:
        """Return the static catalog of actions this plugin exposes.

        Implementations should return a fresh list each call so callers
        can mutate the result safely. The host validates each
        descriptor's ``callable`` and ``config_model`` ImportStrings at
        construction time, so misconfigured paths fail loud during
        registry load rather than at request time.
        """


# ---------------------------------------------------------------------------
# Analysis plugin
# ---------------------------------------------------------------------------


#: Possible statuses for a single ``AnalysisResultItem``. ``fail`` is
#: the worst, ``warn`` is intermediate, ``pass`` is healthy — the
#: Doctor panel groups results in that order and the report's
#: ``overall_status`` is the worst observed across all items.
AnalysisResultStatus = typing.Literal['pass', 'warn', 'fail']


class AnalysisResultItem(pydantic.BaseModel):
    """A single finding emitted by an :class:`AnalysisPlugin`.

    Stable per-plugin ``slug`` lets scoring policies and the UI refer to
    a result across runs. ``description`` is rendered as Markdown by
    the Project Doctor panel.
    """

    slug: str
    title: str
    description: str
    status: AnalysisResultStatus


class AnalysisPlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.  Analysis plugins inspect a
    project (via its links, third-party-service connections, and any
    per-plugin credentials) and return a list of pass/warn/fail
    findings that surface in the Project Doctor panel and feed the
    ``analysis_result`` scoring-policy category.
    """

    manifest: PluginManifest

    @abc.abstractmethod
    async def analyze(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[AnalysisResultItem]: ...
