import datetime
import typing

import cypherantic
import pydantic
import slugify
from jsonschema_models.models import Schema

__all__ = [
    'MODEL_TYPES',
    'APIKey',
    'Blueprint',
    'BlueprintAssignment',
    'BlueprintEdge',
    'EmptyRelationship',
    'Environment',
    'Group',
    'GroupEdge',
    'Node',
    'OAuthIdentity',
    'Organization',
    'PasswordChangeRequest',
    'Permission',
    'Project',
    'ProjectType',
    'ResourcePermission',
    'Role',
    'RoleEdge',
    'Schema',
    'Session',
    'TOTPSecret',
    'Team',
    'TokenMetadata',
    'User',
    'UserCreate',
    'UserResponse',
]


class Blueprint(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str | None = None
    type: typing.Literal[
        'Organization', 'Team', 'Environment', 'ProjectType', 'Project'
    ]
    description: str | None = None
    enabled: bool = True
    priority: int = 0
    filter: dict[str, typing.Any] | None = None
    json_schema: Schema
    version: int = 0

    @pydantic.model_validator(mode='after')
    def generate_and_validate_slug(self) -> typing.Self:
        """Generate slug from name if not provided and validate it."""
        if self.slug is None:
            self.slug = slugify.slugify(self.name)
        else:
            self.slug = self.slug.lower()

        # Validate slug format
        if not self.slug:
            raise ValueError('Slug cannot be empty')
        if not all(c.islower() or c.isdigit() or c == '-' for c in self.slug):
            raise ValueError(
                'Slug must contain only lowercase letters, '
                'numbers, and hyphens'
            )
        return self

    @pydantic.field_validator('json_schema', mode='before')
    @classmethod
    def validate_json_schema(cls, value: typing.Any) -> Schema:
        if isinstance(value, str):
            return Schema.model_validate_json(value)
        elif isinstance(value, dict):
            return Schema.model_validate(value)
        elif isinstance(value, Schema):
            return value
        raise ValueError('Invalid JSON Schema value')

    @pydantic.field_serializer('json_schema')
    def serialize_json_schema(self, value: Schema) -> str:
        return value.model_dump_json(indent=0)


class BlueprintAssignment(pydantic.BaseModel):
    cypherantic_config: typing.ClassVar[cypherantic.RelationshipConfig] = (
        cypherantic.RelationshipConfig(rel_type='BLUEPRINT')
    )
    priority: int = 0


class BlueprintEdge(typing.NamedTuple):
    node: Blueprint
    properties: BlueprintAssignment


class Node(pydantic.BaseModel):
    """Base model for Cypherantic nodes.

    The `icon` attribute can either be a URL or a CSS class name

    """

    model_config = pydantic.ConfigDict(extra='allow')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None


class Organization(Node): ...


class Team(Node):
    member_of: typing.Annotated[
        Organization,
        cypherantic.Relationship(rel_type='MANAGED_BY', direction='OUTGOING'),
    ]


class Environment(Node): ...


class ProjectType(Node): ...


class Project(Node):
    team: typing.Annotated[
        Team,
        cypherantic.Relationship(rel_type='OWNED_BY', direction='OUTGOING'),
    ]
    project_type: typing.Annotated[
        ProjectType,
        cypherantic.Relationship(rel_type='TYPE', direction='OUTGOING'),
    ]
    environments: typing.Annotated[
        list[Environment],
        cypherantic.Relationship(rel_type='DEPLOYED_IN', direction='OUTGOING'),
    ] = []
    links: dict[str, pydantic.HttpUrl]
    urls: dict[str, pydantic.HttpUrl]
    identifiers: dict[str, int | str]


# Model type mapping for schema generation
MODEL_TYPES: dict[str, type[pydantic.BaseModel]] = {
    'Organization': Organization,
    'Team': Team,
    'Environment': Environment,
    'ProjectType': ProjectType,
    'Project': Project,
}


# Authentication and Authorization Models


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

    groups: typing.Annotated[
        list['GroupEdge'],
        cypherantic.Relationship(rel_type='MEMBER_OF', direction='OUTGOING'),
    ] = []
    roles: typing.Annotated[
        list['RoleEdge'],
        cypherantic.Relationship(rel_type='HAS_ROLE', direction='OUTGOING'),
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
        encryptor: typing.Any,  # TokenEncryption from imbi.auth.encryption
    ) -> None:
        """Set OAuth tokens with encryption (Phase 5).

        Args:
            access: Plaintext access token from OAuth provider
            refresh: Plaintext refresh token from OAuth provider
            encryptor: TokenEncryption instance for encrypting tokens
        """
        self.access_token = encryptor.encrypt(access)
        self.refresh_token = encryptor.encrypt(refresh)

    def get_decrypted_tokens(
        self,
        encryptor: typing.Any,  # TokenEncryption from imbi.auth.encryption
    ) -> tuple[str | None, str | None]:
        """Get decrypted OAuth tokens (Phase 5).

        Args:
            encryptor: TokenEncryption instance for decrypting tokens

        Returns:
            Tuple of (access_token, refresh_token) in plaintext
        """
        return (
            encryptor.decrypt(self.access_token),
            encryptor.decrypt(self.refresh_token),
        )


class Group(Node):
    """Group for organizing users and assigning roles."""

    parent: typing.Annotated[
        'Group | None',
        cypherantic.Relationship(
            rel_type='PARENT_GROUP', direction='OUTGOING'
        ),
    ] = None
    roles: typing.Annotated[
        list['Role'],
        cypherantic.Relationship(
            rel_type='ASSIGNED_ROLE', direction='OUTGOING'
        ),
    ] = []


class Role(Node):
    """Role for grouping permissions."""

    priority: int = 0
    is_system: bool = False

    permissions: typing.Annotated[
        list['Permission'],
        cypherantic.Relationship(rel_type='GRANTS', direction='OUTGOING'),
    ] = []
    parent_role: typing.Annotated[
        'Role | None',
        cypherantic.Relationship(
            rel_type='INHERITS_FROM', direction='OUTGOING'
        ),
    ] = None


class EmptyRelationship(pydantic.BaseModel):
    """Empty relationship properties for simple relationships without data."""

    ...  # Explicitly empty - no relationship properties needed


class GroupEdge(typing.NamedTuple):
    """Edge type for User->Group MEMBER_OF relationships."""

    node: Group
    properties: EmptyRelationship


class RoleEdge(typing.NamedTuple):
    """Edge type for User->Role HAS_ROLE relationships."""

    node: Role
    properties: EmptyRelationship


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

    The secret field is encrypted at rest using Fernet symmetric encryption
    for security. Use set_encrypted_secret() and get_decrypted_secret()
    to handle encryption/decryption.
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
        encryptor: typing.Any,  # TokenEncryption from imbi.auth.encryption
    ) -> None:
        """Encrypt and set the TOTP secret (Phase 5).

        Args:
            plaintext_secret: Base32-encoded TOTP secret in plaintext
            encryptor: TokenEncryption instance for encrypting the secret

        """
        self.secret = encryptor.encrypt(plaintext_secret) or ''

    def get_decrypted_secret(
        self,
        encryptor: typing.Any,  # TokenEncryption from imbi.auth.encryption
    ) -> str:
        """Get decrypted TOTP secret (Phase 5).

        Args:
            encryptor: TokenEncryption instance for decrypting the secret

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
    scopes: list[str] = []  # e.g., ['project:read', 'blueprint:read']

    # Lifecycle
    created_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None
    last_rotated: datetime.datetime | None = None
    revoked: bool = False
    revoked_at: datetime.datetime | None = None

    user: typing.Annotated[
        User,
        cypherantic.Relationship(rel_type='OWNED_BY', direction='OUTGOING'),
    ]


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

    groups: list[Group] = []
    roles: list[Role] = []


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
