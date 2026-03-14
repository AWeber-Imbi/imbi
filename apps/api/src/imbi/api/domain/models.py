"""API-specific domain models.

These models are used exclusively by imbi-api for authentication,
authorization, user management, and file uploads. They were moved
from imbi-common to keep the shared library focused on models
needed across all Imbi services.
"""

import datetime
import typing

import cypherantic
import pydantic
from imbi_common import models

__all__ = [
    'APIKey',
    'ClientCredential',
    'ClientCredentialCreate',
    'ClientCredentialCreateResponse',
    'ClientCredentialResponse',
    'EmptyRelationship',
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
    'ServiceApplication',
    'ServiceApplicationCreate',
    'ServiceApplicationResponse',
    'Session',
    'TOTPSecret',
    'ThirdPartyService',
    'TokenMetadata',
    'Upload',
    'User',
    'UserCreate',
    'UserResponse',
]


class User(pydantic.BaseModel):
    """User account for authentication and authorization."""

    model_config = pydantic.ConfigDict(extra='ignore')

    email: pydantic.EmailStr
    display_name: str
    password_hash: str | None = None
    is_active: bool = True
    is_admin: bool = False
    is_service_account: bool = False
    created_at: datetime.datetime
    last_login: datetime.datetime | None = None
    avatar_url: pydantic.HttpUrl | None = None

    organizations: typing.Annotated[
        list['OrganizationEdge'],
        cypherantic.Relationship(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []


class OAuthIdentity(pydantic.BaseModel):
    """OAuth provider identity linked to a user."""

    model_config = pydantic.ConfigDict(extra='ignore')

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
        cypherantic.Relationship(
            rel_type='OAUTH_IDENTITY', direction='OUTGOING'
        ),
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


class MembershipProperties(pydantic.BaseModel):
    """Properties on User->Organization MEMBER_OF relationships."""

    cypherantic_config: typing.ClassVar[cypherantic.RelationshipConfig] = (
        cypherantic.RelationshipConfig(rel_type='MEMBER_OF')
    )
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
        list['Permission'],
        cypherantic.Relationship(rel_type='GRANTS', direction='OUTGOING'),
    ] = []  # noqa: RUF012
    parent_role: typing.Annotated[
        'Role | None',
        cypherantic.Relationship(
            rel_type='INHERITS_FROM', direction='OUTGOING'
        ),
    ] = None


class EmptyRelationship(pydantic.BaseModel):
    """Empty relationship properties for simple relationships."""

    pass  # Explicitly empty - no relationship properties needed


class Permission(pydantic.BaseModel):
    """Permission for a specific resource action."""

    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    resource_type: str
    action: str
    description: str | None = None


class ResourcePermission(pydantic.BaseModel):
    """Resource-level permission for CAN_ACCESS relationships."""

    cypherantic_config: typing.ClassVar[cypherantic.RelationshipConfig] = (
        cypherantic.RelationshipConfig(rel_type='CAN_ACCESS')
    )
    actions: list[str] = []
    granted_at: datetime.datetime
    granted_by: str


class TokenMetadata(pydantic.BaseModel):
    """Metadata for JWT tokens to enable revocation."""

    model_config = pydantic.ConfigDict(extra='ignore')

    jti: str
    token_type: typing.Literal['access', 'refresh']
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    user: typing.Annotated[
        User | None,
        cypherantic.Relationship(rel_type='ISSUED_TO', direction='OUTGOING'),
    ] = None


class TOTPSecret(pydantic.BaseModel):
    """TOTP secret for MFA/2FA (Phase 5).

    The secret field is encrypted at rest using Fernet symmetric
    encryption for security. Use set_encrypted_secret() and
    get_decrypted_secret() to handle encryption/decryption.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    secret: str  # Encrypted Base32-encoded TOTP secret
    enabled: bool = False
    backup_codes: list[str] = []  # Hashed backup codes (Argon2)
    created_at: datetime.datetime
    last_used: datetime.datetime | None = None

    user: typing.Annotated[
        User,
        cypherantic.Relationship(rel_type='MFA_FOR', direction='OUTGOING'),
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


class Session(pydantic.BaseModel):
    """User session for tracking concurrent sessions (Phase 5)."""

    model_config = pydantic.ConfigDict(extra='ignore')

    session_id: str  # Unique session identifier (UUID)
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime.datetime
    last_activity: datetime.datetime
    expires_at: datetime.datetime

    user: typing.Annotated[
        User,
        cypherantic.Relationship(rel_type='SESSION_FOR', direction='OUTGOING'),
    ]


class APIKey(pydantic.BaseModel):
    """API key for programmatic access (Phase 5)."""

    model_config = pydantic.ConfigDict(extra='ignore')

    key_id: str  # Public key identifier (format: 'ik_...')
    key_hash: str  # Hashed secret (Argon2)
    name: str  # Human-readable name
    description: str | None = None

    # Permissions
    scopes: list[str] = []

    # Lifecycle
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    user: typing.Annotated[
        User | None,
        cypherantic.Relationship(rel_type='OWNED_BY', direction='OUTGOING'),
    ] = None


class Upload(pydantic.BaseModel):
    """Metadata for an uploaded file stored in S3."""

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str
    filename: str
    content_type: str
    size: int
    s3_key: str
    has_thumbnail: bool = False
    thumbnail_s3_key: str | None = None
    uploaded_by: str
    created_at: datetime.datetime

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


class ServiceAccount(pydantic.BaseModel):
    """Service account for machine-to-machine authentication."""

    model_config = pydantic.ConfigDict(extra='ignore')

    slug: str
    display_name: str
    description: str | None = None
    is_active: bool = True
    created_at: datetime.datetime
    last_authenticated: datetime.datetime | None = None

    organizations: typing.Annotated[
        list['OrganizationEdge'],
        cypherantic.Relationship(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []


class ServiceAccountCreate(pydantic.BaseModel):
    """Request model for creating service accounts."""

    slug: str = pydantic.Field(
        ...,
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
        description='Unique slug identifier (lowercase, hyphens)',
    )
    display_name: str = pydantic.Field(..., min_length=1, max_length=128)
    description: str | None = None
    is_active: bool = True


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


class ClientCredential(pydantic.BaseModel):
    """OAuth2 client credential for service accounts."""

    model_config = pydantic.ConfigDict(extra='ignore')

    client_id: str
    client_secret_hash: str
    name: str
    description: str | None = None
    scopes: list[str] = []
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    service_account: typing.Annotated[
        ServiceAccount | None,
        cypherantic.Relationship(rel_type='OWNED_BY', direction='OUTGOING'),
    ] = None


class ClientCredentialCreate(pydantic.BaseModel):
    """Request model for creating client credentials."""

    name: str = pydantic.Field(
        ...,
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
        cypherantic.Relationship(
            rel_type='BELONGS_TO',
            direction='OUTGOING',
        ),
    ]
    team: typing.Annotated[
        models.Team | None,
        cypherantic.Relationship(
            rel_type='MANAGED_BY',
            direction='OUTGOING',
        ),
    ] = None
    vendor: str
    service_url: pydantic.HttpUrl | None = None
    category: str | None = None
    status: typing.Literal[
        'active',
        'deprecated',
        'evaluating',
        'inactive',
    ] = 'active'
    links: dict[str, pydantic.HttpUrl] = {}  # noqa: RUF012
    identifiers: dict[str, int | str] = {}  # noqa: RUF012


SECRET_MASK = '********'


class ServiceApplication(pydantic.BaseModel):
    """OAuth2 application registered in a third-party service."""

    model_config = pydantic.ConfigDict(extra='ignore')

    slug: str
    name: str
    description: str | None = None
    app_type: str  # e.g. github_app, pagerduty_oauth
    application_url: str | None = None
    client_id: str
    client_secret: str  # Fernet-encrypted at rest
    scopes: list[str] = []
    webhook_secret: str | None = None  # Fernet-encrypted
    private_key: str | None = None  # Fernet-encrypted (PEM)
    signing_secret: str | None = None  # Fernet-encrypted
    settings: dict[str, str | int | bool] = {}
    status: typing.Literal['active', 'inactive', 'revoked'] = 'active'

    def encrypt_secrets(
        self,
        encryptor: typing.Any,  # TokenEncryption
    ) -> None:
        """Encrypt all secret fields in place."""
        self.client_secret = encryptor.encrypt(self.client_secret)
        if self.webhook_secret is not None:
            self.webhook_secret = encryptor.encrypt(self.webhook_secret)
        if self.private_key is not None:
            self.private_key = encryptor.encrypt(self.private_key)
        if self.signing_secret is not None:
            self.signing_secret = encryptor.encrypt(self.signing_secret)

    def mask_secrets(self) -> None:
        """Replace encrypted secret fields with mask for responses."""
        self.client_secret = SECRET_MASK
        if self.webhook_secret is not None:
            self.webhook_secret = SECRET_MASK
        if self.private_key is not None:
            self.private_key = SECRET_MASK
        if self.signing_secret is not None:
            self.signing_secret = SECRET_MASK


class ServiceApplicationCreate(pydantic.BaseModel):
    """Request model for creating a service application."""

    slug: str = pydantic.Field(
        ...,
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    name: str = pydantic.Field(..., min_length=1, max_length=128)
    description: str | None = None
    app_type: str = pydantic.Field(..., min_length=1, max_length=64)
    application_url: str | None = None
    client_id: str = pydantic.Field(..., min_length=1)
    client_secret: str = pydantic.Field(..., min_length=1)
    scopes: list[str] = pydantic.Field(default_factory=list)
    webhook_secret: str | None = None
    private_key: str | None = None
    signing_secret: str | None = None
    settings: dict[str, str | int | bool] = pydantic.Field(
        default_factory=dict,
    )
    status: typing.Literal['active', 'inactive', 'revoked'] = 'active'


class ServiceApplicationResponse(pydantic.BaseModel):
    """Response model for service applications (secrets masked)."""

    slug: str
    name: str
    description: str | None = None
    app_type: str
    application_url: str | None = None
    client_id: str
    client_secret: str = SECRET_MASK
    scopes: list[str] = []
    webhook_secret: str | None = None
    private_key: str | None = None
    signing_secret: str | None = None
    settings: dict[str, str | int | bool] = {}
    status: str = 'active'


class OAuth2TokenResponse(pydantic.BaseModel):
    """OAuth2 token response per RFC 6749."""

    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    scope: str | None = None
    refresh_token: str | None = None
