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


class PluginManifest(pydantic.BaseModel):
    slug: str
    name: str
    description: str | None = None
    plugin_type: typing.Literal[
        'configuration', 'logs', 'identity', 'deployment'
    ]
    auth_type: typing.Literal['api_token', 'oauth2', 'oidc', 'aws-iam-ic'] = (
        'api_token'
    )
    api_version: int = 1
    cacheable: bool = True
    supports_histogram: bool = False
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
