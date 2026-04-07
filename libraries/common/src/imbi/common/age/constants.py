"""Schema definitions for Apache AGE graph.

AGE stores graph data in PostgreSQL tables.  Each vertex label gets
its own table under the graph schema (e.g. ``imbi."User"``).
Unique constraints and indexes are expressed as standard PostgreSQL
DDL on the ``properties`` JSONB column of those tables.

The ``SETUP`` list is executed once during :func:`initialize` to
create the AGE extension, graph, and load the extension into the
session.

The ``INDEXES`` list contains ``CREATE UNIQUE INDEX`` / ``CREATE INDEX``
statements that mirror the Neo4j constraints from the previous
implementation.
"""

GRAPH_NAME = 'imbi'

# -- Bootstrap DDL (run first, in order) -----------------------------------

SETUP: list[str] = [
    'CREATE EXTENSION IF NOT EXISTS age',
    "LOAD 'age'",
    'SET search_path = ag_catalog, "$user", public',
]

# -- Ensure the graph exists -----------------------------------------------
# AGE's create_graph() raises an error if the graph already exists,
# so we guard with a DO block.

ENSURE_GRAPH: str = (
    f'DO $$ BEGIN'  # noqa: S608
    f' IF NOT EXISTS ('
    f' SELECT 1 FROM ag_catalog.ag_graph'
    f" WHERE name = '{GRAPH_NAME}'"
    f' ) THEN'
    f" PERFORM ag_catalog.create_graph('{GRAPH_NAME}');"
    f' END IF;'
    f' END $$;'
)

# -- Vertex label bootstrap ------------------------------------------------
# AGE requires labels to exist before you can create indexes on their
# tables.  We create each label via a no-op Cypher MATCH so that the
# underlying table is created, then we can safely add indexes.

_LABELS: list[str] = [
    'Blueprint',
    'Team',
    'LinkDefinition',
    'Project',
    'Conversation',
    'Message',
    'ServiceAccount',
    'ClientCredential',
    'User',
    'Role',
    'Permission',
    'TokenMetadata',
    'OAuthIdentity',
    'Session',
    'APIKey',
    'ThirdPartyService',
    'ServiceApplication',
    'Upload',
    'Webhook',
    'WebhookRule',
    'WebhookImplementation',
    'TOTPSecret',
    'Environment',
    'ProjectType',
    'Organization',
]

ENSURE_LABELS: list[str] = [
    f"SELECT ag_catalog.create_vlabel('{GRAPH_NAME}', '{label}')"
    for label in _LABELS
]

# -- Unique constraints and indexes ----------------------------------------
# These are PostgreSQL indexes on the AGE vertex tables.  Column
# expressions reference ``properties ->> 'field'`` for single-field
# indexes and ``(properties ->> 'f1', properties ->> 'f2')`` for
# composite uniqueness.
#
# Index names follow the pattern:  <label>_<field(s)>_<unique|idx>

INDEXES: list[str] = [
    # Blueprints — composite unique on (name, type)
    f'CREATE UNIQUE INDEX IF NOT EXISTS blueprint_name_type_unique '
    f'ON {GRAPH_NAME}."Blueprint" '
    f"((properties ->> 'name'), (properties ->> 'type'))",
    # Teams
    f'CREATE UNIQUE INDEX IF NOT EXISTS team_slug_unique '
    f'ON {GRAPH_NAME}."Team" '
    f"((properties ->> 'slug'))",
    # Link Definitions
    f'CREATE UNIQUE INDEX IF NOT EXISTS link_definition_slug_unique '
    f'ON {GRAPH_NAME}."LinkDefinition" '
    f"((properties ->> 'slug'))",
    # Projects
    f'CREATE UNIQUE INDEX IF NOT EXISTS project_id_unique '
    f'ON {GRAPH_NAME}."Project" '
    f"((properties ->> 'id'))",
    f'CREATE INDEX IF NOT EXISTS project_name_idx '
    f'ON {GRAPH_NAME}."Project" '
    f"((properties ->> 'name'))",
    f'CREATE INDEX IF NOT EXISTS project_slug_idx '
    f'ON {GRAPH_NAME}."Project" '
    f"((properties ->> 'slug'))",
    # Conversations
    f'CREATE UNIQUE INDEX IF NOT EXISTS conversation_id_unique '
    f'ON {GRAPH_NAME}."Conversation" '
    f"((properties ->> 'id'))",
    f'CREATE INDEX IF NOT EXISTS conversation_user_email_idx '
    f'ON {GRAPH_NAME}."Conversation" '
    f"((properties ->> 'user_email'))",
    f'CREATE INDEX IF NOT EXISTS conversation_updated_at_idx '
    f'ON {GRAPH_NAME}."Conversation" '
    f"((properties ->> 'updated_at'))",
    # Messages
    f'CREATE UNIQUE INDEX IF NOT EXISTS message_id_unique '
    f'ON {GRAPH_NAME}."Message" '
    f"((properties ->> 'id'))",
    f'CREATE INDEX IF NOT EXISTS message_conversation_id_idx '
    f'ON {GRAPH_NAME}."Message" '
    f"((properties ->> 'conversation_id'))",
    # Service Accounts
    f'CREATE UNIQUE INDEX IF NOT EXISTS service_account_slug_unique '
    f'ON {GRAPH_NAME}."ServiceAccount" '
    f"((properties ->> 'slug'))",
    # Client Credentials
    f'CREATE UNIQUE INDEX IF NOT EXISTS '
    f'client_credential_client_id_unique '
    f'ON {GRAPH_NAME}."ClientCredential" '
    f"((properties ->> 'client_id'))",
    # Users
    f'CREATE UNIQUE INDEX IF NOT EXISTS user_username_unique '
    f'ON {GRAPH_NAME}."User" '
    f"((properties ->> 'username'))",
    f'CREATE UNIQUE INDEX IF NOT EXISTS user_email_unique '
    f'ON {GRAPH_NAME}."User" '
    f"((properties ->> 'email'))",
    f'CREATE INDEX IF NOT EXISTS user_active_idx '
    f'ON {GRAPH_NAME}."User" '
    f"((properties ->> 'is_active'))",
    # Roles
    f'CREATE UNIQUE INDEX IF NOT EXISTS role_slug_unique '
    f'ON {GRAPH_NAME}."Role" '
    f"((properties ->> 'slug'))",
    f'CREATE INDEX IF NOT EXISTS role_priority_idx '
    f'ON {GRAPH_NAME}."Role" '
    f"((properties ->> 'priority'))",
    # Permissions
    f'CREATE UNIQUE INDEX IF NOT EXISTS permission_name_unique '
    f'ON {GRAPH_NAME}."Permission" '
    f"((properties ->> 'name'))",
    f'CREATE INDEX IF NOT EXISTS permission_resource_idx '
    f'ON {GRAPH_NAME}."Permission" '
    f"((properties ->> 'resource_type'))",
    # JWT Tokens
    f'CREATE UNIQUE INDEX IF NOT EXISTS token_jti_unique '
    f'ON {GRAPH_NAME}."TokenMetadata" '
    f"((properties ->> 'jti'))",
    # OAuth Identities — composite unique
    f'CREATE UNIQUE INDEX IF NOT EXISTS '
    f'oauth_identity_provider_user_unique '
    f'ON {GRAPH_NAME}."OAuthIdentity" '
    f"((properties ->> 'provider'), "
    f"(properties ->> 'provider_user_id'))",
    f'CREATE INDEX IF NOT EXISTS oauth_identity_email_idx '
    f'ON {GRAPH_NAME}."OAuthIdentity" '
    f"((properties ->> 'email'))",
    # Sessions
    f'CREATE UNIQUE INDEX IF NOT EXISTS session_id_unique '
    f'ON {GRAPH_NAME}."Session" '
    f"((properties ->> 'session_id'))",
    f'CREATE INDEX IF NOT EXISTS session_expires_idx '
    f'ON {GRAPH_NAME}."Session" '
    f"((properties ->> 'expires_at'))",
    # API Keys
    f'CREATE UNIQUE INDEX IF NOT EXISTS api_key_id_unique '
    f'ON {GRAPH_NAME}."APIKey" '
    f"((properties ->> 'key_id'))",
    f'CREATE INDEX IF NOT EXISTS api_key_revoked_idx '
    f'ON {GRAPH_NAME}."APIKey" '
    f"((properties ->> 'revoked'))",
    # Third-Party Services
    f'CREATE UNIQUE INDEX IF NOT EXISTS '
    f'third_party_service_slug_unique '
    f'ON {GRAPH_NAME}."ThirdPartyService" '
    f"((properties ->> 'slug'))",
    f'CREATE INDEX IF NOT EXISTS third_party_service_status_idx '
    f'ON {GRAPH_NAME}."ThirdPartyService" '
    f"((properties ->> 'status'))",
    # Service Applications
    f'CREATE INDEX IF NOT EXISTS service_app_slug_idx '
    f'ON {GRAPH_NAME}."ServiceApplication" '
    f"((properties ->> 'slug'))",
    f'CREATE INDEX IF NOT EXISTS service_app_status_idx '
    f'ON {GRAPH_NAME}."ServiceApplication" '
    f"((properties ->> 'status'))",
    # Uploads
    f'CREATE UNIQUE INDEX IF NOT EXISTS upload_id_unique '
    f'ON {GRAPH_NAME}."Upload" '
    f"((properties ->> 'id'))",
]
