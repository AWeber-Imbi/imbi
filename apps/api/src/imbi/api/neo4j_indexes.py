"""API-specific Neo4j indexes for auth and upload models."""

import typing

INDEXES: list[typing.LiteralString] = [
    # Users
    'CREATE CONSTRAINT user_username_unique IF NOT EXISTS '
    'FOR (n:User) REQUIRE n.username IS UNIQUE;',
    'CREATE CONSTRAINT user_email_unique IF NOT EXISTS '
    'FOR (n:User) REQUIRE n.email IS UNIQUE;',
    'CREATE INDEX user_active IF NOT EXISTS FOR (n:User) ON (n.is_active);',
    # Roles
    'CREATE CONSTRAINT role_slug_unique IF NOT EXISTS '
    'FOR (n:Role) REQUIRE n.slug IS UNIQUE;',
    'CREATE INDEX role_priority IF NOT EXISTS FOR (n:Role) ON (n.priority);',
    # Permissions
    'CREATE CONSTRAINT permission_name_unique IF NOT EXISTS '
    'FOR (n:Permission) REQUIRE n.name IS UNIQUE;',
    'CREATE INDEX permission_resource IF NOT EXISTS '
    'FOR (n:Permission) ON (n.resource_type);',
    # JWT Tokens
    'CREATE CONSTRAINT token_jti_unique IF NOT EXISTS '
    'FOR (n:TokenMetadata) REQUIRE n.jti IS UNIQUE;',
    # OAuth Identities
    'CREATE CONSTRAINT oauth_identity_provider_user_unique '
    'IF NOT EXISTS FOR (n:OAuthIdentity) '
    'REQUIRE (n.provider, n.provider_user_id) IS UNIQUE;',
    'CREATE INDEX oauth_identity_email IF NOT EXISTS '
    'FOR (n:OAuthIdentity) ON (n.email);',
    # Sessions
    'CREATE CONSTRAINT session_id_unique IF NOT EXISTS '
    'FOR (n:Session) REQUIRE n.session_id IS UNIQUE;',
    'CREATE INDEX session_expires IF NOT EXISTS '
    'FOR (n:Session) ON (n.expires_at);',
    # API Keys
    'CREATE CONSTRAINT api_key_id_unique IF NOT EXISTS '
    'FOR (n:APIKey) REQUIRE n.key_id IS UNIQUE;',
    'CREATE INDEX api_key_revoked IF NOT EXISTS '
    'FOR (n:APIKey) ON (n.revoked);',
    # Uploads
    'CREATE CONSTRAINT upload_id_unique IF NOT EXISTS '
    'FOR (n:Upload) REQUIRE n.id IS UNIQUE;',
]
