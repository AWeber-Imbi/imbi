"""API-specific domain models.

These models are used exclusively by imbi-api for authentication,
authorization, user management, and file uploads. They were moved
from imbi-common to keep the shared library focused on models
needed across all Imbi services.
"""

import datetime
import json
import typing

import pydantic
from imbi_common import graph, models

__all__ = [
    'SECRET_FIELDS',
    'APIKey',
    'CapabilityAssignment',
    'CapabilityAssignmentsUpdate',
    'CapabilityToggle',
    'ClientCredential',
    'ClientCredentialCreate',
    'ClientCredentialCreateResponse',
    'ClientCredentialResponse',
    'ConfigKeyResponse',
    'ConfigKeyValueResponse',
    'EmptyRelationship',
    'ExistsInCreate',
    'ExistsInResponse',
    'InstalledPluginResponse',
    'IntegrationCreate',
    'IntegrationCredentialsUpdate',
    'IntegrationResponse',
    'IntegrationUpdate',
    'LocalAuthConfig',
    'LogEntryResponse',
    'LogHistogramBucketResponse',
    'LogResultResponse',
    'LoginProviderUpdate',
    'MembershipProperties',
    'OAuth2TokenResponse',
    'OAuthClient',
    'OAuthClientRegistrationRequest',
    'OAuthClientRegistrationResponse',
    'OAuthIdentity',
    'OrgMembership',
    'OrganizationEdge',
    'PasswordChangeRequest',
    'Permission',
    'PluginRegistrationUpdate',
    'ProjectIntegrationAssignment',
    'ProjectIntegrationsUpdate',
    'ResourcePermission',
    'Role',
    'ServiceAccount',
    'ServiceAccountCreate',
    'ServiceAccountResponse',
    'Session',
    'TOTPSecret',
    'TeamMembership',
    'TokenMetadata',
    'Upload',
    'User',
    'UserCreate',
    'UserResponse',
    'WebhookCreate',
    'WebhookResponse',
    'WebhookRuleCreate',
    'WebhookRuleResponse',
    'WebhookUpdate',
]


class User(models.GraphModel):
    """User account for authentication and authorization."""

    email: pydantic.EmailStr
    display_name: str
    password_hash: str | None = None
    is_active: bool = True
    is_admin: bool = False
    is_service_account: bool = False
    last_login: datetime.datetime | None = None
    avatar_url: pydantic.HttpUrl | None = None
    email_notifications: bool = True

    organizations: typing.Annotated[
        list[OrganizationEdge],
        models.Edge(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []  # noqa: RUF012


class OAuthIdentity(models.GraphModel):
    """OAuth provider identity linked to a user.

    Keyed by ``(provider_slug, provider_user_id)`` so two configured
    IdPs of the same ``oauth_app_type`` (e.g. two OIDC issuers or two
    GHE instances) cannot collide on ``provider_user_id`` when their
    ``sub`` values happen to overlap. ``provider_slug`` is the
    ``ServiceApplication.slug`` of the row that minted the identity.
    See AWeber-Imbi/imbi-api#255.
    """

    provider_slug: str
    provider_user_id: str
    email: pydantic.EmailStr
    display_name: str
    avatar_url: pydantic.HttpUrl | None = None

    # OAuth tokens (Phase 5: NOW ENCRYPTED)
    # These fields store base64-encoded encrypted tokens
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime.datetime | None = None

    # Metadata
    linked_at: datetime.datetime
    last_used: datetime.datetime
    raw_profile: dict[str, typing.Any] | None = None

    # Relationship to User
    user: typing.Annotated[
        User,
        models.Edge(rel_type='OAUTH_IDENTITY', direction='OUTGOING'),
    ]

    def set_encrypted_tokens(
        self,
        access: str | None,
        refresh: str | None,
        encryptor: typing.Any,  # TokenEncryption
    ) -> None:
        """Set OAuth tokens with encryption (Phase 5).

        Args:
            access: Plaintext access token from OAuth provider
            refresh: Plaintext refresh token from OAuth provider
            encryptor: TokenEncryption instance for encrypting tokens

        Raises:
            ValueError: If encryption fails for a non-None token.
        """
        encrypted_access = (
            encryptor.encrypt(access) if access is not None else None
        )
        encrypted_refresh = (
            encryptor.encrypt(refresh) if refresh is not None else None
        )
        if access is not None and encrypted_access is None:
            raise ValueError('Failed to encrypt OAuth access token')
        if refresh is not None and encrypted_refresh is None:
            raise ValueError('Failed to encrypt OAuth refresh token')
        self.access_token = encrypted_access
        self.refresh_token = encrypted_refresh

    def get_decrypted_tokens(
        self,
        encryptor: typing.Any,  # TokenEncryption
    ) -> tuple[str | None, str | None]:
        """Get decrypted OAuth tokens (Phase 5).

        Args:
            encryptor: TokenEncryption instance for decrypting tokens

        Returns:
            Tuple of (access_token, refresh_token) in plaintext

        Raises:
            ValueError: If decryption fails for a non-None token.
        """
        access_token: str | None = None
        refresh_token: str | None = None
        if self.access_token is not None:
            access_token = encryptor.decrypt(self.access_token)
            if access_token is None:
                raise ValueError('Failed to decrypt OAuth access token')
        if self.refresh_token is not None:
            refresh_token = encryptor.decrypt(self.refresh_token)
            if refresh_token is None:
                raise ValueError('Failed to decrypt OAuth refresh token')
        return (access_token, refresh_token)


class LocalAuthConfig(models.GraphModel):
    """Singleton config row for local password authentication.

    A single row keyed by the literal ``'global'`` controls whether
    email/password sign-in is offered alongside OAuth providers.
    """

    key: typing.Literal['global'] = 'global'
    enabled: bool = True
    # Keep ``| None`` to stay invariant-compatible with
    # ``GraphModel.updated_at`` — pydantic mutable fields can't be
    # narrowed past the parent (basedpyright strict flags it as
    # ``reportIncompatibleVariableOverride``). The default_factory
    # always produces a datetime so callers still see a non-None
    # value in practice.
    updated_at: datetime.datetime | None = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )


class MembershipProperties(pydantic.BaseModel):
    """Properties on User->Organization MEMBER_OF relationships."""

    role: str  # Role slug


class OrganizationEdge(typing.NamedTuple):
    """Edge type for User->Organization MEMBER_OF relationships."""

    node: models.Organization
    properties: MembershipProperties


class OrgMembership(pydantic.BaseModel):
    """Organization membership with role for API responses."""

    model_config = pydantic.ConfigDict(extra='ignore')
    organization_name: str
    organization_slug: str
    role: str


class TeamMembership(pydantic.BaseModel):
    """Team membership for API responses."""

    model_config = pydantic.ConfigDict(extra='ignore')
    team_name: str
    team_slug: str
    organization_slug: str


class Role(models.Node):  # type: ignore[misc]
    """Role for grouping permissions."""

    priority: int = 0
    is_system: bool = False

    permissions: typing.Annotated[
        list[Permission],
        models.Edge(rel_type='GRANTS', direction='OUTGOING'),
    ] = []  # noqa: RUF012
    parent_role: typing.Annotated[
        Role | None,
        models.Edge(rel_type='INHERITS_FROM', direction='OUTGOING'),
    ] = None


class EmptyRelationship(pydantic.BaseModel):
    """Empty relationship properties for simple relationships."""

    pass  # Explicitly empty - no relationship properties needed


class Permission(models.GraphModel):
    """Permission for a specific resource action."""

    name: str
    resource_type: str
    action: str
    description: str | None = None


class ResourcePermission(pydantic.BaseModel):
    """Resource-level permission for CAN_ACCESS relationships."""

    actions: list[str] = []
    granted_at: datetime.datetime
    granted_by: str


class TokenMetadata(models.GraphModel):
    """Metadata for JWT tokens to enable revocation."""

    jti: str
    token_type: typing.Literal['access', 'refresh']
    family_id: str | None = None
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    user: typing.Annotated[
        User | None,
        models.Edge(rel_type='ISSUED_TO', direction='OUTGOING'),
    ] = None


class TOTPSecret(models.GraphModel):
    """TOTP secret for MFA/2FA (Phase 5).

    The secret field is encrypted at rest using Fernet symmetric
    encryption for security. Use set_encrypted_secret() and
    get_decrypted_secret() to handle encryption/decryption.
    """

    secret: str  # Encrypted Base32-encoded TOTP secret
    enabled: bool = False
    backup_codes: list[str] = []  # noqa: RUF012 — Argon2 hashed
    last_used: datetime.datetime | None = None

    user: typing.Annotated[
        User,
        models.Edge(rel_type='MFA_FOR', direction='OUTGOING'),
    ]

    def set_encrypted_secret(
        self,
        plaintext_secret: str,
        encryptor: typing.Any,  # TokenEncryption
    ) -> None:
        """Encrypt and set the TOTP secret (Phase 5).

        Args:
            plaintext_secret: Base32-encoded TOTP secret in plaintext
            encryptor: TokenEncryption instance for encrypting

        """
        encrypted = encryptor.encrypt(plaintext_secret)
        if encrypted is None:
            raise ValueError('Failed to encrypt TOTP secret')
        self.secret = encrypted

    def get_decrypted_secret(
        self,
        encryptor: typing.Any,  # TokenEncryption
    ) -> str:
        """Get decrypted TOTP secret (Phase 5).

        Args:
            encryptor: TokenEncryption instance for decrypting

        Returns:
            Base32-encoded TOTP secret in plaintext

        Raises:
            ValueError: If decryption fails or returns None

        """
        decrypted = encryptor.decrypt(self.secret)
        if decrypted is None:
            raise ValueError('Failed to decrypt TOTP secret')
        return str(decrypted)


class Session(models.GraphModel):
    """User session for tracking concurrent sessions (Phase 5)."""

    session_id: str  # Unique session identifier (UUID)
    ip_address: str | None = None
    user_agent: str | None = None
    last_activity: datetime.datetime
    expires_at: datetime.datetime

    user: typing.Annotated[
        User,
        models.Edge(rel_type='SESSION_FOR', direction='OUTGOING'),
    ]


class APIKey(models.GraphModel):
    """API key for programmatic access (Phase 5)."""

    key_id: str  # Public key identifier (format: 'ik_...')
    key_hash: str  # Hashed secret (Argon2)
    name: str  # Human-readable name
    description: str | None = None

    # Permissions
    scopes: list[str] = []  # noqa: RUF012

    # Lifecycle
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    user: typing.Annotated[
        User | None,
        models.Edge(rel_type='OWNED_BY', direction='OUTGOING'),
    ] = None


class Upload(models.GraphModel):
    """Metadata for an uploaded file stored in S3."""

    filename: str
    content_type: str
    size: int
    s3_key: str
    has_thumbnail: bool = False
    thumbnail_s3_key: str | None = None
    uploaded_by: str

    @pydantic.field_validator('size')
    @classmethod
    def validate_size(cls, value: int) -> int:
        """Validate that file size is non-negative."""
        if value < 0:
            raise ValueError('size must be non-negative')
        return value

    @pydantic.model_validator(mode='after')
    def validate_thumbnail_consistency(self) -> typing.Self:
        """Validate has_thumbnail and thumbnail_s3_key."""
        if self.has_thumbnail and not self.thumbnail_s3_key:
            raise ValueError(
                'thumbnail_s3_key is required when has_thumbnail is True'
            )
        if not self.has_thumbnail and self.thumbnail_s3_key is not None:
            raise ValueError(
                'thumbnail_s3_key must be empty when has_thumbnail is False'
            )
        return self


class UserCreate(pydantic.BaseModel):
    """Request model for creating users."""

    email: pydantic.EmailStr
    display_name: str
    password: str | None = None
    is_active: bool = True
    is_admin: bool = False
    is_service_account: bool = False
    email_notifications: bool = True
    organization_slug: str
    role_slug: str


class UserResponse(pydantic.BaseModel):
    """Response model for users (excludes password_hash)."""

    model_config = pydantic.ConfigDict(extra='ignore')

    email: pydantic.EmailStr
    display_name: str
    is_active: bool
    is_admin: bool
    is_service_account: bool
    created_at: datetime.datetime
    last_login: datetime.datetime | None = None
    avatar_url: pydantic.HttpUrl | None = None
    email_notifications: bool = True

    organizations: list[OrgMembership] = []


class CurrentUserResponse(UserResponse):
    """Response model for the authenticated user's own profile.

    Extends ``UserResponse`` with the caller's effective permission set
    and team memberships so the UI can gate features and offer
    membership-scoped filters in a single request. Only exposed via
    ``GET /users/me`` — the per-email endpoint deliberately omits
    permissions to avoid disclosing one user's grants to another.
    """

    permissions: list[str] = []
    teams: list[TeamMembership] = []


class PasswordChangeRequest(pydantic.BaseModel):
    """Request model for changing user passwords."""

    current_password: str | None = None
    new_password: str

    @pydantic.field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """Validate password meets minimum security requirements."""
        if len(value) < 12:
            raise ValueError('Password must be at least 12 characters')
        if not any(c.isupper() for c in value):
            raise ValueError('Password must contain at least one uppercase')
        if not any(c.islower() for c in value):
            raise ValueError('Password must contain at least one lowercase')
        if not any(c.isdigit() for c in value):
            raise ValueError('Password must contain at least one digit')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in value):
            raise ValueError('Password must contain at least one special')
        return value


class ServiceAccount(models.GraphModel):
    """Service account for machine-to-machine authentication."""

    slug: str
    display_name: str
    description: str | None = None
    is_active: bool = True
    last_authenticated: datetime.datetime | None = None
    avatar_url: str | None = None

    organizations: typing.Annotated[
        list[OrganizationEdge],
        models.Edge(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []  # noqa: RUF012


class ServiceAccountCreate(pydantic.BaseModel):
    """Request model for creating service accounts."""

    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
        description='Unique slug identifier (lowercase, hyphens)',
    )
    display_name: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    is_active: bool = True
    organization_slug: str
    role_slug: str


class ServiceAccountResponse(pydantic.BaseModel):
    """Response model for service accounts."""

    model_config = pydantic.ConfigDict(extra='ignore')

    slug: str
    display_name: str
    description: str | None = None
    is_active: bool
    created_at: datetime.datetime
    last_authenticated: datetime.datetime | None = None
    avatar_url: str | None = None
    organizations: list[OrgMembership] = []


class ClientCredential(models.GraphModel):
    """OAuth2 client credential for service accounts."""

    client_id: str
    client_secret_hash: str
    name: str
    description: str | None = None
    scopes: list[str] = []  # noqa: RUF012
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    service_account: typing.Annotated[
        ServiceAccount | None,
        models.Edge(rel_type='OWNED_BY', direction='OUTGOING'),
    ] = None


class ClientCredentialCreate(pydantic.BaseModel):
    """Request model for creating client credentials."""

    name: str = pydantic.Field(
        min_length=1,
        max_length=128,
        description='Human-readable name',
    )
    description: str | None = None
    scopes: list[str] = pydantic.Field(
        default_factory=list,
        description='Permission scopes (empty = all)',
    )
    expires_in_days: int | None = pydantic.Field(
        default=None,
        description='Days until expiration (None = never)',
        ge=1,
    )


class ClientCredentialResponse(pydantic.BaseModel):
    """Response model for client credentials (without secret)."""

    client_id: str
    name: str
    description: str | None = None
    scopes: list[str] = []
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool
    revoked_at: datetime.datetime | None = None


class ClientCredentialCreateResponse(pydantic.BaseModel):
    """Response model for client credential creation (secret shown once)."""

    client_id: str
    client_secret: str
    name: str
    description: str | None = None
    scopes: list[str] = []
    expires_at: datetime.datetime | None = None


SECRET_FIELDS = (
    'client_secret',
    'webhook_secret',
    'private_key',
    'signing_secret',
    'plugin_credentials',
)


_VALID_INTEGRATION_STATUSES = typing.Literal[
    'active',
    'deprecated',
    'evaluating',
    'inactive',
]


# -- Integration models ---------------------------------------------------


class CapabilityToggle(pydantic.BaseModel):
    """Per-capability state on an Integration: enabled + capability options."""

    enabled: bool
    options: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class IntegrationCreate(pydantic.BaseModel):
    """Request model for creating an Integration (a plugin instance)."""

    plugin: str = pydantic.Field(min_length=1, max_length=64)
    name: str = pydantic.Field(min_length=1, max_length=128)
    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    team_slug: str | None = None
    description: str | None = None
    icon: str | None = None
    vendor: str | None = None
    service_url: pydantic.HttpUrl | None = None
    category: str | None = None
    status: _VALID_INTEGRATION_STATUSES = 'active'
    #: Integration-level option values (validated against the plugin
    #: manifest's ``options`` at the endpoint).
    options: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    #: Plaintext credential values, encrypted before persistence. Keyed
    #: by the manifest's ``credentials`` field names. Write-only.
    credentials: dict[str, str] = pydantic.Field(default_factory=dict)
    #: Initial per-capability toggles. Capabilities omitted here default
    #: to their manifest ``default_enabled``.
    capabilities: dict[str, CapabilityToggle] = pydantic.Field(
        default_factory=dict
    )
    links: dict[str, str] = pydantic.Field(default_factory=dict)
    identifiers: dict[str, int | str] = pydantic.Field(default_factory=dict)


class IntegrationUpdate(pydantic.BaseModel):
    """Request model for patching an Integration.

    All fields are optional; only those present in the request body are
    applied (tri-state via ``model_fields_set``). Credentials are updated
    through the dedicated credentials endpoint, not here.
    """

    name: str | None = pydantic.Field(
        default=None, min_length=1, max_length=128
    )
    team_slug: str | None = None
    description: str | None = None
    icon: str | None = None
    vendor: str | None = None
    service_url: pydantic.HttpUrl | None = None
    category: str | None = None
    status: _VALID_INTEGRATION_STATUSES | None = None
    options: dict[str, typing.Any] | None = None
    capabilities: dict[str, CapabilityToggle] | None = None
    links: dict[str, str] | None = None
    identifiers: dict[str, int | str] | None = None


class IntegrationCredentialsUpdate(pydantic.BaseModel):
    """Write-only credential patch for an Integration.

    Maps credential field name to a new plaintext value; ``None`` (or an
    empty string) removes the field. Fields not present are preserved.
    """

    credentials: dict[str, str | None] = pydantic.Field(default_factory=dict)


class LoginProviderUpdate(pydantic.BaseModel):
    """Promote/demote an Integration as the org's SSO login provider."""

    used_as_login: bool


class IntegrationResponse(pydantic.BaseModel):
    """Response model for an Integration (no credential values)."""

    model_config = pydantic.ConfigDict(extra='ignore')

    #: Stable node id. ``None`` only for legacy Integrations created before
    #: ids were persisted; the identity connect flow keys off this.
    id: str | None = None
    plugin: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    vendor: str | None = None
    service_url: str | None = None
    category: str | None = None
    status: str = 'active'
    options: dict[str, typing.Any] = {}
    capabilities: dict[str, CapabilityToggle] = {}
    #: Names of the credential fields currently populated (never values).
    credential_fields: list[str] = []
    #: Values of populated, non-secret credential fields (``secret=False``
    #: in the plugin manifest). Secret values are never included.
    credential_values: dict[str, str] = {}
    links: dict[str, typing.Any] = {}
    identifiers: dict[str, typing.Any] = {}
    organization: dict[str, typing.Any] | None = None
    team: dict[str, typing.Any] | None = None
    #: Whether this Integration is the organization's SSO login provider.
    used_as_login: bool = False


# -- Admin plugin (installed package) models ------------------------------


class PluginRegistrationUpdate(pydantic.BaseModel):
    """Request model for enabling/disabling an installed plugin package."""

    enabled: bool


class InstalledPluginResponse(pydantic.BaseModel):
    """Response model for an installed plugin package.

    The manifest is serialized as pure data (capability ``handler``
    bindings are excluded by the manifest itself) plus the package
    identity and registration state.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    slug: str
    name: str
    description: str | None = None
    api_version: int
    auth_type: str
    options: list[dict[str, typing.Any]] = []
    credentials: list[dict[str, typing.Any]] = []
    capabilities: list[dict[str, typing.Any]] = []
    data_types: list[dict[str, typing.Any]] = []
    vertex_labels: list[dict[str, typing.Any]] = []
    edge_labels: list[dict[str, typing.Any]] = []
    package_name: str
    package_version: str
    enabled: bool = False


# -- Capability assignment models -----------------------------------------


class CapabilityAssignment(pydantic.BaseModel):
    """One project-type assignment of an Integration's capability.

    Binds ``(:ProjectType)-[:USES {capability}]->(:Integration)``.
    """

    project_type_slug: str
    default: bool = False
    options: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    env_payloads: dict[str, dict[str, typing.Any]] = pydantic.Field(
        default_factory=dict
    )
    identity_integration_slug: str | None = None


class CapabilityAssignmentsUpdate(pydantic.BaseModel):
    """Replace-all body for a capability's project-type assignments."""

    assignments: list[CapabilityAssignment] = pydantic.Field(
        default_factory=list
    )


class ProjectIntegrationAssignment(pydantic.BaseModel):
    """One project-level ``USES`` override of an Integration capability."""

    integration_slug: str
    capability: str
    default: bool = False
    options: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    env_payloads: dict[str, dict[str, typing.Any]] = pydantic.Field(
        default_factory=dict
    )
    identity_integration_slug: str | None = None


class ProjectIntegrationsUpdate(pydantic.BaseModel):
    """Replace-all body for a project's ``USES`` overrides."""

    assignments: list[ProjectIntegrationAssignment] = pydantic.Field(
        default_factory=list
    )


class LifecycleSyncError(pydantic.BaseModel):
    """One non-fatal failure encountered during a lifecycle sync."""

    project_id: str
    detail: str


class LifecycleSyncSummary(pydantic.BaseModel):
    """Aggregate outcome of a lifecycle push-sync run.

    A sync re-dispatches each project's ``on_project_updated`` -- an
    upsert that creates the remote when missing and updates it
    otherwise -- so the per-project outcome is the plugin's
    ``LifecycleResult.status``: ``synced`` counts ``ok`` results,
    ``skipped`` counts ``skipped`` (e.g. an unmapped team), and
    ``failed`` counts ``failed`` results plus dispatches that raised
    (each captured in ``errors``).
    """

    projects: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[LifecycleSyncError] = []


# -- Configuration / Logs response models ---------------------------------


class ConfigKeyResponse(pydantic.BaseModel):
    """Response model for a configuration key (no value)."""

    key: str
    data_type: str
    last_modified: datetime.datetime | None = None
    secret: bool = False


class ConfigKeyValueResponse(ConfigKeyResponse):
    """Response model for a configuration key with its value."""

    value: str


class LogEntryResponse(pydantic.BaseModel):
    """Response model for a single log entry."""

    model_config = pydantic.ConfigDict(extra='ignore')

    timestamp: datetime.datetime
    message: str
    level: str | None = None
    raw: dict[str, typing.Any] = {}


class LogHistogramBucketResponse(pydantic.BaseModel):
    """A single time bucket in a log histogram response."""

    timestamp: datetime.datetime
    count: int
    levels: dict[str, int] = {}


class LogResultResponse(pydantic.BaseModel):
    """Paginated log search result."""

    entries: list[LogEntryResponse]
    next_cursor: str | None = None
    total: int | None = None
    warnings: list[str] = []


class OAuth2TokenResponse(pydantic.BaseModel):
    """OAuth2 token response per RFC 6749."""

    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    scope: str | None = None
    refresh_token: str | None = None


class OAuthClient(models.GraphModel):
    """A dynamically-registered OAuth2 client (RFC 7591).

    Created by the ``/auth/register`` endpoint when an MCP client (or any
    OAuth client) self-registers, and read by ``/auth/authorize`` and
    ``/auth/token`` to validate the client and its redirect URIs. Only
    public clients (``token_endpoint_auth_method='none'``, PKCE-protected)
    are supported today, so no secret is stored.
    """

    client_id: str
    client_name: str | None = None
    redirect_uris: list[str]
    grant_types: list[str] = [  # noqa: RUF012
        'authorization_code',
        'refresh_token',
    ]
    response_types: list[str] = ['code']  # noqa: RUF012
    token_endpoint_auth_method: str = 'none'
    scope: str | None = None


class OAuthClientRegistrationRequest(pydantic.BaseModel):
    """RFC 7591 dynamic client registration request."""

    redirect_uris: list[str]
    client_name: str | None = None
    grant_types: list[str] = [
        'authorization_code',
        'refresh_token',
    ]
    response_types: list[str] = ['code']
    token_endpoint_auth_method: str = 'none'
    scope: str | None = None


class OAuthClientRegistrationResponse(pydantic.BaseModel):
    """RFC 7591 dynamic client registration response."""

    client_id: str
    client_name: str | None = None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str | None = None
    client_id_issued_at: int


# -- Webhook models -------------------------------------------------------


class WebhookRuleCreate(pydantic.BaseModel):
    """A single rule within a webhook (no ordinal — position is implicit)."""

    filter_expression: str = pydantic.Field(min_length=1)
    handler: str = pydantic.Field(
        min_length=1,
        description='Python callable in dotted import syntax',
    )
    handler_config: dict[str, typing.Any] | list[typing.Any] = pydantic.Field(
        default_factory=dict,
        description='Structured configuration passed to the handler',
    )


class WebhookCreate(pydantic.BaseModel):
    """Request model for creating a webhook.

    The slug, id, and notification_path are system-generated.
    """

    name: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = None
    secret: str | None = None
    integration_slug: str | None = None
    identifier_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that extracts the project identifier from the '
            'webhook payload (e.g. /repository/id).'
        ),
    )
    user_subject_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that locates the external identity subject '
            '(e.g. /deployment/creator/id) used to resolve the Imbi user.'
        ),
    )
    user_type_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that locates the sender account type (e.g. '
            "/sender/type). When it resolves to 'Bot' the identity lookup "
            'is skipped, since bot senders are never Imbi users.'
        ),
    )
    identity_integration_slug: str | None = pydantic.Field(
        default=None,
        description=(
            'Optional override for the identity integration slug used to '
            'resolve the Imbi user; falls back to identity integrations '
            'attached to the integration when unset.'
        ),
    )
    event_type_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'Resolves the activity-feed event type for each webhook. '
            'Values starting with "/" are JSON pointers evaluated against '
            'the request body; otherwise the value is treated as an HTTP '
            'header name (case-insensitive). When the header is absent, '
            'the literal selector value is used as the label.'
        ),
    )
    rules: list[WebhookRuleCreate] = pydantic.Field(
        default_factory=list,
    )

    @pydantic.model_validator(mode='after')
    def validate_identifier_selector(self) -> typing.Self:
        """identifier_selector requires an integration."""
        if self.identifier_selector and not self.integration_slug:
            raise ValueError('identifier_selector requires integration_slug')
        if self.user_subject_selector and not self.integration_slug:
            raise ValueError('user_subject_selector requires integration_slug')
        if self.user_type_selector and not self.integration_slug:
            raise ValueError('user_type_selector requires integration_slug')
        if self.identity_integration_slug and not self.integration_slug:
            raise ValueError(
                'identity_integration_slug requires integration_slug'
            )
        if self.event_type_selector and not self.integration_slug:
            raise ValueError('event_type_selector requires integration_slug')
        return self


class WebhookUpdate(pydantic.BaseModel):
    """Patchable fields for a webhook (JSON Patch target document).

    The slug is editable. The id and notification_path are
    system-managed and rejected at the endpoint level if a patch
    operation targets them.
    """

    name: str = pydantic.Field(min_length=1, max_length=128)
    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    description: str | None = None
    icon: str | None = None
    secret: str | None = None
    integration_slug: str | None = None
    identifier_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that extracts the project identifier from the '
            'webhook payload (e.g. /repository/id).'
        ),
    )
    user_subject_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that locates the external identity subject '
            '(e.g. /deployment/creator/id) used to resolve the Imbi user.'
        ),
    )
    user_type_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'JSON Pointer that locates the sender account type (e.g. '
            "/sender/type). When it resolves to 'Bot' the identity lookup "
            'is skipped, since bot senders are never Imbi users.'
        ),
    )
    identity_integration_slug: str | None = pydantic.Field(
        default=None,
        description=(
            'Optional override for the identity integration slug used to '
            'resolve the Imbi user; falls back to identity integrations '
            'attached to the integration when unset.'
        ),
    )
    event_type_selector: str | None = pydantic.Field(
        default=None,
        description=(
            'Resolves the activity-feed event type for each webhook. '
            'Values starting with "/" are JSON pointers evaluated against '
            'the request body; otherwise the value is treated as an HTTP '
            'header name (case-insensitive). When the header is absent, '
            'the literal selector value is used as the label.'
        ),
    )
    rules: list[WebhookRuleCreate] = pydantic.Field(
        default_factory=list,
    )

    @pydantic.model_validator(mode='after')
    def validate_identifier_selector(self) -> typing.Self:
        """identifier_selector requires an integration."""
        if self.identifier_selector and not self.integration_slug:
            raise ValueError('identifier_selector requires integration_slug')
        if self.user_subject_selector and not self.integration_slug:
            raise ValueError('user_subject_selector requires integration_slug')
        if self.user_type_selector and not self.integration_slug:
            raise ValueError('user_type_selector requires integration_slug')
        if self.identity_integration_slug and not self.integration_slug:
            raise ValueError(
                'identity_integration_slug requires integration_slug'
            )
        if self.event_type_selector and not self.integration_slug:
            raise ValueError('event_type_selector requires integration_slug')
        return self


class WebhookRuleResponse(pydantic.BaseModel):
    """Rule in a webhook response (no ordinal exposed)."""

    filter_expression: str
    handler: str
    handler_config: dict[str, typing.Any] | list[typing.Any] = pydantic.Field(
        default_factory=dict,
    )


class WebhookResponse(pydantic.BaseModel):
    """Response model for a webhook."""

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    notification_path: str
    integration: dict[str, typing.Any] | None = None
    identifier_selector: str | None = None
    user_subject_selector: str | None = None
    user_type_selector: str | None = None
    identity_integration_slug: str | None = None
    event_type_selector: str | None = None
    rules: list[WebhookRuleResponse] = []

    @classmethod
    def from_graph_record(
        cls,
        record: dict[str, typing.Any],
    ) -> WebhookResponse:
        """Build a WebhookResponse from a graph query record."""
        webhook = graph.parse_agtype(record['webhook'])

        raw_rules: list[dict[str, typing.Any] | None] = (
            graph.parse_agtype(record.get('rules')) or []
        )
        rules: list[WebhookRuleResponse] = []
        for r in raw_rules:
            if r:
                raw_config: str = r.get('handler_config', '{}')
                config: dict[str, typing.Any] | list[typing.Any]
                try:
                    config = json.loads(raw_config) if raw_config else {}
                except json.JSONDecodeError, TypeError:
                    config = {}
                rules.append(
                    WebhookRuleResponse(
                        filter_expression=str(r['filter_expression']),
                        handler=str(r['handler']),
                        handler_config=config,
                    )
                )

        tps = record.get('tps')
        if tps:
            tps = graph.parse_agtype(tps)

        return cls(
            id=webhook['id'],
            name=webhook['name'],
            slug=webhook['slug'],
            description=webhook.get('description'),
            icon=webhook.get('icon'),
            notification_path=webhook['notification_path'],
            integration=tps,
            identifier_selector=graph.parse_agtype(
                record.get('identifier_selector')
            ),
            user_subject_selector=graph.parse_agtype(
                record.get('user_subject_selector')
            ),
            user_type_selector=graph.parse_agtype(
                record.get('user_type_selector')
            ),
            identity_integration_slug=graph.parse_agtype(
                record.get('identity_integration_slug')
            ),
            event_type_selector=graph.parse_agtype(
                record.get('event_type_selector')
            ),
            rules=rules,
        )


# -- EXISTS_IN models ------------------------------------------------------


class ExistsInCreate(pydantic.BaseModel):
    """Request model for creating a Project EXISTS_IN link."""

    integration_slug: str
    identifier: str = pydantic.Field(min_length=1)
    canonical_url: str | None = None
    #: Optional human dashboard URL; persisted into ``Project.links``
    #: keyed by the service slug (not stored on the edge).  Validated as a
    #: URL at the request boundary so a malformed value can't poison the
    #: project's ``links`` map (``dict[str, AnyUrl]``), which is
    #: re-validated on every project read.
    dashboard_url: pydantic.AnyUrl | None = None


class ExistsInResponse(pydantic.BaseModel):
    """Response model for a Project EXISTS_IN link."""

    integration_slug: str
    integration_name: str
    identifier: str
    canonical_url: str | None = None
    #: Human dashboard URL read from ``Project.links`` (service slug key).
    dashboard_url: str | None = None
