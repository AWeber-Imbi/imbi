"""Plugin base classes and shared data models."""

import abc
import datetime
import typing

import pydantic


class PluginOption(pydantic.BaseModel):
    name: str
    label: str
    description: str | None = None
    type: typing.Literal['string', 'integer', 'boolean', 'secret'] = 'string'
    required: bool = False
    default: str | int | bool | None = None
    choices: list[str] | None = None


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


class PluginManifest(pydantic.BaseModel):
    slug: str
    name: str
    description: str | None = None
    plugin_type: typing.Literal[
        'configuration',
        'logs',
        'identity',
        'deployment',
        'lifecycle',
        'webhook',
    ]
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


class PluginContext(pydantic.BaseModel):
    project_id: str
    project_slug: str
    org_slug: str
    team_slug: str | None = None
    environment: str | None = None
    assignment_options: dict[str, typing.Any] = {}
    # Project's external links (e.g. ``{"github-repository": "https://..."}``).
    # Populated by the host so plugins can derive per-project state (e.g. the
    # GitHub owner/repo) from the link map instead of duplicating it as
    # plugin options on every assignment.
    project_links: dict[str, str] = {}
    # Slugs of every ``ProjectType`` the project is tagged with. Plugins
    # may use these as a discovery hint (e.g. trying each as a candidate
    # GitHub owner) when an explicit link or option isn't supplied.
    project_type_slugs: list[str] = []
    # Per-environment edge properties resolved by the host from the
    # plugin-declared ``DEPLOYS_VIA``-style edge (project edge layered
    # over project-type edge, mirroring how ``assignment_options`` is
    # merged).  Empty when no per-env edge is configured for
    # ``environment``.  Plugin authors should treat absent keys as
    # "fall back to plugin defaults" rather than as a hard error.
    environment_config: dict[str, typing.Any] = {}
    actor_user_id: str | None = None
    identity: IdentityCredentials | None = None


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
        an operator configures the per-environment dispatch edge
        (e.g. ``DEPLOYS_VIA``).  Plugins without a workflow concept
        raise :class:`NotImplementedError`.
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


class LifecyclePlugin(abc.ABC):
    """Plugins must not stash global state.

    A new instance is created per request.  Lifecycle plugins react to
    entity state changes (archive / unarchive today; create / delete may
    follow).  The host invokes them after the authoritative Imbi state
    change has succeeded so a third-party failure does not roll back
    the operator's intent.
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


# ---------------------------------------------------------------------------
# Webhook action plugin
# ---------------------------------------------------------------------------


class WebhookActionPlugin(abc.ABC):
    """Base class for webhook-action plugins.

    Webhook action plugins declare a manifest (slug, credentials,
    optional configuration options) so operators can install and
    configure them like any other plugin.  The host (``imbi-gateway``)
    parses ``WebhookRule.handler`` as ``"<plugin_slug>:<action>"``,
    looks the plugin up in the registry, fetches the decrypted
    per-instance credentials, builds a :class:`PluginContext`, and
    calls :meth:`run_action`.

    Implementations dispatch on the ``action`` parameter; each named
    action is one branch of webhook behaviour (e.g. a SonarQube
    plugin might expose ``'update_project_from_webhook'``).
    """

    manifest: PluginManifest

    @abc.abstractmethod
    async def run_action(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        external_identifier: str,
        action: str,
        action_config: str,
        payload: object,
    ) -> None:
        """Run the named webhook action.

        Arguments:
            ctx: standard plugin context (org/project/team slugs, etc.).
            credentials: decrypted plugin credentials keyed by manifest
                ``CredentialField.name``.
            external_identifier: the value the gateway resolved out of
                the inbound payload via ``IMPLEMENTED_BY.identifier_selector``
                (e.g. a SonarQube ``/project/key``).
            action: the action name parsed from ``WebhookRule.handler``
                after the ``:`` separator.
            action_config: opaque per-rule JSON config; the implementation
                is responsible for validation.
            payload: the raw webhook body.
        """
