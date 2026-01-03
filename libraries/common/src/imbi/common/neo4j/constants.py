"""Constants for the Neo4J integration."""

_EMBEDDING_INDEX_CONFIG = """\
{
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
}
"""

INDEXES: list[str] = [
    # Blueprints
    'CREATE CONSTRAINT blueprint_pkey IF NOT EXISTS FOR (n:Blueprint) '
    'REQUIRE (n.name, n.type) IS UNIQUE;',
    # Users
    'CREATE CONSTRAINT user_username_unique IF NOT EXISTS FOR (n:User) '
    'REQUIRE n.username IS UNIQUE;',
    'CREATE CONSTRAINT user_email_unique IF NOT EXISTS FOR (n:User) '
    'REQUIRE n.email IS UNIQUE;',
    'CREATE INDEX user_active IF NOT EXISTS FOR (n:User) ON (n.is_active);',
    # Groups
    'CREATE CONSTRAINT group_slug_unique IF NOT EXISTS FOR (n:Group) '
    'REQUIRE n.slug IS UNIQUE;',
    # Roles
    'CREATE CONSTRAINT role_slug_unique IF NOT EXISTS FOR (n:Role) '
    'REQUIRE n.slug IS UNIQUE;',
    'CREATE INDEX role_priority IF NOT EXISTS FOR (n:Role) ON (n.priority);',
    # Permissions
    'CREATE CONSTRAINT permission_name_unique IF NOT EXISTS '
    'FOR (n:Permission) REQUIRE n.name IS UNIQUE;',
    'CREATE INDEX permission_resource IF NOT EXISTS FOR (n:Permission) '
    'ON (n.resource_type);',
    # JWT Tokens
    'CREATE CONSTRAINT token_jti_unique IF NOT EXISTS '
    'FOR (n:TokenMetadata) REQUIRE n.jti IS UNIQUE;',
    # OAuth Identities
    'CREATE CONSTRAINT oauth_identity_provider_user_unique IF NOT EXISTS '
    'FOR (n:OAuthIdentity) '
    'REQUIRE (n.provider, n.provider_user_id) IS UNIQUE;',
    'CREATE INDEX oauth_identity_email IF NOT EXISTS '
    'FOR (n:OAuthIdentity) ON (n.email);',
    # Phase 5: TOTP Secrets
    # Note: 'user' is a relationship (MFA_FOR), not a property
    # Queries should traverse the relationship instead of using an index
    # Phase 5: Sessions
    'CREATE CONSTRAINT session_id_unique IF NOT EXISTS '
    'FOR (n:Session) REQUIRE n.session_id IS UNIQUE;',
    # Note: 'user' is a relationship (SESSION_FOR), not a property
    'CREATE INDEX session_expires IF NOT EXISTS '
    'FOR (n:Session) ON (n.expires_at);',
    # Phase 5: API Keys
    'CREATE CONSTRAINT api_key_id_unique IF NOT EXISTS '
    'FOR (n:APIKey) REQUIRE n.key_id IS UNIQUE;',
    # Note: 'user' is a relationship (OWNED_BY), not a property
    'CREATE INDEX api_key_revoked IF NOT EXISTS '
    'FOR (n:APIKey) ON (n.revoked);',
]
