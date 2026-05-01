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
    'ClientCredential',
    'ClientCredentialCreate',
    'ClientCredentialCreateResponse',
    'ClientCredentialResponse',
    'EmptyRelationship',
    'ExistsInCreate',
    'ExistsInResponse',
    'LocalAuthConfig',
    'MembershipProperties',
    'OAuth2TokenResponse',
    'OAuthIdentity',
    'OrgMembership',
    'OrganizationEdge',
    'PasswordChangeRequest',
    'Permission',
    'ResourcePermission',
    'Role',
    'ServiceAccount',
    'ServiceAccountCreate',
    'ServiceAccountResponse',
    'ServiceApplicationCreate',
    'ServiceApplicationResponse',
    'ServiceApplicationSecrets',
    'Session',
    'TOTPSecret',
    'ThirdPartyService',
    'ThirdPartyServiceCreate',
    'ThirdPartyServiceResponse',
    'ThirdPartyServiceUpdate',
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
    """OAuth provider identity linked to a user."""

    provider: typing.Literal['google', 'github', 'oidc']
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


class ThirdPartyService(models.Node):  # type: ignore[misc]
    """An external SaaS platform or managed service.

    Examples: Lob, FullStory, Stripe, Datadog, PagerDuty.
    """

    organization: typing.Annotated[
        models.Organization,
        models.Edge(
            rel_type='BELONGS_TO',
            direction='OUTGOING',
        ),
    ]
    team: typing.Annotated[
        models.Team | None,
        models.Edge(
            rel_type='MANAGED_BY',
            direction='OUTGOING',
        ),
    ] = None
    vendor: str
    service_url: pydantic.HttpUrl | None = None
    api_endpoint: pydantic.HttpUrl | None = None
    authorization_endpoint: pydantic.HttpUrl | None = None
    token_endpoint: pydantic.HttpUrl | None = None
    revoke_endpoint: pydantic.HttpUrl | None = None
    use_pkce: bool | None = None
    category: str | None = None
    status: typing.Literal[
        'active',
        'deprecated',
        'evaluating',
        'inactive',
    ] = 'active'
    links: dict[str, pydantic.HttpUrl] = {}  # noqa: RUF012
    identifiers: dict[str, int | str] = {}  # noqa: RUF012


_VALID_SERVICE_STATUSES = typing.Literal[
    'active',
    'deprecated',
    'evaluating',
    'inactive',
]


class ThirdPartyServiceCreate(pydantic.BaseModel):
    """Request model for creating a third-party service."""

    team_slug: str | None = None
    name: str = pydantic.Field(min_length=1, max_length=128)
    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    vendor: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = None
    service_url: pydantic.HttpUrl | None = None
    api_endpoint: pydantic.HttpUrl | None = None
    authorization_endpoint: pydantic.HttpUrl | None = None
    token_endpoint: pydantic.HttpUrl | None = None
    revoke_endpoint: pydantic.HttpUrl | None = None
    use_pkce: bool | None = None
    category: str | None = None
    status: _VALID_SERVICE_STATUSES = 'active'
    links: dict[str, str] = pydantic.Field(
        default_factory=dict,
    )
    identifiers: dict[str, int | str] = pydantic.Field(
        default_factory=dict,
    )


class ThirdPartyServiceUpdate(pydantic.BaseModel):
    """Request model for updating a third-party service.

    Designed for GET-modify-PUT: the client fetches the full resource,
    modifies fields, and sends the complete object back. All fields
    that exist on the response are required (no silent defaults).
    """

    team_slug: str | None = None
    name: str = pydantic.Field(min_length=1, max_length=128)
    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    vendor: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    icon: str | None = None
    service_url: pydantic.HttpUrl | None = None
    api_endpoint: pydantic.HttpUrl | None = None
    authorization_endpoint: pydantic.HttpUrl | None = None
    token_endpoint: pydantic.HttpUrl | None = None
    revoke_endpoint: pydantic.HttpUrl | None = None
    use_pkce: bool | None = None
    category: str | None = None
    status: _VALID_SERVICE_STATUSES
    links: dict[str, str] = pydantic.Field(default_factory=dict)
    identifiers: dict[str, int | str] = pydantic.Field(
        default_factory=dict,
    )


class ThirdPartyServiceResponse(pydantic.BaseModel):
    """Response model for a third-party service."""

    model_config = pydantic.ConfigDict(extra='allow')

    name: str
    slug: str
    vendor: str
    description: str | None = None
    icon: str | None = None
    service_url: str | None = None
    api_endpoint: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    revoke_endpoint: str | None = None
    use_pkce: bool | None = None
    category: str | None = None
    status: str = 'active'
    links: dict[str, typing.Any] = {}
    identifiers: dict[str, typing.Any] = {}
    organization: dict[str, typing.Any] | None = None
    team: dict[str, typing.Any] | None = None


SECRET_FIELDS = (
    'client_secret',
    'webhook_secret',
    'private_key',
    'signing_secret',
)


_OAuthAppType = typing.Literal['google', 'github', 'oidc']
_AppUsage = typing.Literal['login', 'integration', 'both']


def validate_login_app_fields(
    usage: str,
    oauth_app_type: str | None,
    client_id: str | None,
    issuer_url: str | None,
    allowed_domains: list[str],
) -> None:
    """Cross-field validation for login-shaped service applications."""
    if usage in ('login', 'both'):
        if oauth_app_type is None:
            raise ValueError(
                "oauth_app_type is required when usage is 'login' or 'both'"
            )
        if not client_id:
            raise ValueError(
                "client_id is required when usage is 'login' or 'both'"
            )
        if oauth_app_type == 'oidc' and not issuer_url:
            raise ValueError(
                "issuer_url is required when oauth_app_type is 'oidc'"
            )
    if allowed_domains and oauth_app_type != 'google':
        raise ValueError(
            "allowed_domains is only meaningful for oauth_app_type='google'"
        )


class ServiceApplicationCreate(pydantic.BaseModel):
    """Request model for creating a service application."""

    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    name: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    app_type: str = pydantic.Field(min_length=1, max_length=64)
    application_url: str | None = None
    callback_url: pydantic.HttpUrl | None = None
    client_id: str = pydantic.Field(min_length=1)
    client_secret: str = pydantic.Field(min_length=1)
    scopes: list[str] = pydantic.Field(default_factory=list)
    webhook_secret: str | None = None
    private_key: str | None = None
    signing_secret: str | None = None
    settings: dict[str, str | int | bool] = pydantic.Field(
        default_factory=dict,
    )
    status: typing.Literal['active', 'inactive', 'revoked'] = 'active'
    usage: _AppUsage = 'integration'
    oauth_app_type: _OAuthAppType | None = None
    issuer_url: str | None = None
    allowed_domains: list[str] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode='after')
    def _validate_login_fields(self) -> typing.Self:
        validate_login_app_fields(
            self.usage,
            self.oauth_app_type,
            self.client_id,
            self.issuer_url,
            self.allowed_domains,
        )
        return self


class ServiceApplicationResponse(pydantic.BaseModel):
    """Response model for service applications (no secrets)."""

    slug: str
    name: str
    description: str | None = None
    app_type: str
    application_url: str | None = None
    callback_url: str | None = None
    client_id: str
    scopes: list[str] = []
    settings: dict[str, str | int | bool] = {}
    status: str = 'active'
    usage: _AppUsage = 'integration'
    oauth_app_type: _OAuthAppType | None = None
    issuer_url: str | None = None
    allowed_domains: list[str] = []
    is_global: bool = False


class ServiceApplicationSecrets(pydantic.BaseModel):
    """Response model for application secrets (decrypted)."""

    client_secret: str
    webhook_secret: str | None = None
    private_key: str | None = None
    signing_secret: str | None = None


class OAuth2TokenResponse(pydantic.BaseModel):
    """OAuth2 token response per RFC 6749."""

    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    scope: str | None = None
    refresh_token: str | None = None


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
    third_party_service_slug: str | None = None
    identifier_selector: str | None = pydantic.Field(
        default=None,
        description='JSON Path expression to extract project identifier',
    )
    rules: list[WebhookRuleCreate] = pydantic.Field(
        default_factory=list,
    )

    @pydantic.model_validator(mode='after')
    def validate_identifier_selector(self) -> typing.Self:
        """identifier_selector requires a third_party_service."""
        if self.identifier_selector and not self.third_party_service_slug:
            raise ValueError(
                'identifier_selector requires third_party_service_slug'
            )
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
    third_party_service_slug: str | None = None
    identifier_selector: str | None = pydantic.Field(
        default=None,
        description='JSON Path expression to extract project identifier',
    )
    rules: list[WebhookRuleCreate] = pydantic.Field(
        default_factory=list,
    )

    @pydantic.model_validator(mode='after')
    def validate_identifier_selector(self) -> typing.Self:
        """identifier_selector requires a third_party_service."""
        if self.identifier_selector and not self.third_party_service_slug:
            raise ValueError(
                'identifier_selector requires third_party_service_slug'
            )
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

    model_config = pydantic.ConfigDict(extra='allow')

    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    notification_path: str
    third_party_service: dict[str, typing.Any] | None = None
    identifier_selector: str | None = None
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
                except (json.JSONDecodeError, TypeError):
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
            third_party_service=tps,
            identifier_selector=graph.parse_agtype(
                record.get('identifier_selector')
            ),
            rules=rules,
        )


# -- EXISTS_IN models ------------------------------------------------------


class ExistsInCreate(pydantic.BaseModel):
    """Request model for creating a Project EXISTS_IN link."""

    third_party_service_slug: str
    identifier: str = pydantic.Field(min_length=1)
    canonical_link: str | None = None


class ExistsInResponse(pydantic.BaseModel):
    """Response model for a Project EXISTS_IN link."""

    third_party_service_slug: str
    third_party_service_name: str
    identifier: str
    canonical_link: str | None = None
