"""Constants for the Neo4J integration."""

import typing

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
    # Teams
    'CREATE CONSTRAINT team_slug_unique IF NOT EXISTS FOR (n:Team) '
    'REQUIRE n.slug IS UNIQUE;',
    # Link Definitions
    'CREATE CONSTRAINT link_definition_slug_unique '
    'IF NOT EXISTS FOR (n:LinkDefinition) '
    'REQUIRE n.slug IS UNIQUE;',
    # Projects
    'CREATE CONSTRAINT project_id_unique IF NOT EXISTS '
    'FOR (n:Project) REQUIRE n.id IS UNIQUE;',
    'CREATE INDEX project_name IF NOT EXISTS FOR (n:Project) ON (n.name);',
    'CREATE INDEX project_slug IF NOT EXISTS FOR (n:Project) ON (n.slug);',
    # AI Assistant Conversations
    'CREATE CONSTRAINT conversation_id_unique IF NOT EXISTS '
    'FOR (n:Conversation) REQUIRE n.id IS UNIQUE;',
    'CREATE INDEX conversation_user_email IF NOT EXISTS '
    'FOR (n:Conversation) ON (n.user_email);',
    'CREATE INDEX conversation_updated_at IF NOT EXISTS '
    'FOR (n:Conversation) ON (n.updated_at);',
    # AI Assistant Messages
    'CREATE CONSTRAINT message_id_unique IF NOT EXISTS '
    'FOR (n:Message) REQUIRE n.id IS UNIQUE;',
    'CREATE INDEX message_conversation_id IF NOT EXISTS '
    'FOR (n:Message) ON (n.conversation_id);',
    # Service Accounts
    'CREATE CONSTRAINT service_account_slug_unique IF NOT EXISTS '
    'FOR (n:ServiceAccount) REQUIRE n.slug IS UNIQUE;',
    # Client Credentials
    'CREATE CONSTRAINT client_credential_client_id_unique '
    'IF NOT EXISTS '
    'FOR (n:ClientCredential) REQUIRE n.client_id IS UNIQUE;',
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
    # Third-Party Services
    'CREATE CONSTRAINT third_party_service_slug_unique IF NOT EXISTS '
    'FOR (n:ThirdPartyService) REQUIRE n.slug IS UNIQUE;',
    'CREATE INDEX third_party_service_status IF NOT EXISTS '
    'FOR (n:ThirdPartyService) ON (n.status);',
    # Service Applications
    'CREATE INDEX service_app_slug IF NOT EXISTS '
    'FOR (n:ServiceApplication) ON (n.slug);',
    'CREATE INDEX service_app_status IF NOT EXISTS '
    'FOR (n:ServiceApplication) ON (n.status);',
    # Uploads
    'CREATE CONSTRAINT upload_id_unique IF NOT EXISTS '
    'FOR (n:Upload) REQUIRE n.id IS UNIQUE;',
]

# APOC triggers installed at startup via the system database.
# Each entry is passed to `CALL apoc.trigger.install(...)`.
# Triggers replace any existing trigger with the same name, so
# they are safe to re-run on every startup.
TRIGGERS: list[dict[str, typing.Any]] = []
