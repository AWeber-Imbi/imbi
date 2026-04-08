CREATE EXTENSION IF NOT EXISTS age;

SET search_path = ag_catalog, "$user", public;

SELECT ag_catalog.create_graph('imbi');

SELECT ag_catalog.create_vlabel('imbi', 'APIKey');

SELECT ag_catalog.create_vlabel('imbi', 'Blueprint');

SELECT ag_catalog.create_vlabel('imbi', 'ClientCredential');

SELECT ag_catalog.create_vlabel('imbi', 'Conversation');

SELECT ag_catalog.create_vlabel('imbi', 'Environment');

SELECT ag_catalog.create_vlabel('imbi', 'LinkDefinition');

SELECT ag_catalog.create_vlabel('imbi', 'Message');

SELECT ag_catalog.create_vlabel('imbi', 'OAuthIdentity');

SELECT ag_catalog.create_vlabel('imbi', 'Organization');

SELECT ag_catalog.create_vlabel('imbi', 'Permission');

SELECT ag_catalog.create_vlabel('imbi', 'Project');

SELECT ag_catalog.create_vlabel('imbi', 'ProjectType');

SELECT ag_catalog.create_vlabel('imbi', 'Role');

SELECT ag_catalog.create_vlabel('imbi', 'ServiceAccount');

SELECT ag_catalog.create_vlabel('imbi', 'ServiceApplication');

SELECT ag_catalog.create_vlabel('imbi', 'Session');

SELECT ag_catalog.create_vlabel('imbi', 'TOTPSecret');

SELECT ag_catalog.create_vlabel('imbi', 'Team');

SELECT ag_catalog.create_vlabel('imbi', 'ThirdPartyService');

SELECT ag_catalog.create_vlabel('imbi', 'TokenMetadata');

SELECT ag_catalog.create_vlabel('imbi', 'Upload');

SELECT ag_catalog.create_vlabel('imbi', 'User');

SELECT ag_catalog.create_vlabel('imbi', 'Webhook');

SELECT ag_catalog.create_vlabel('imbi', 'WebhookImplementation');

SELECT ag_catalog.create_vlabel('imbi', 'WebhookRule');

CREATE INDEX IF NOT EXISTS api_key_revoked_idx ON imbi."APIKey" (ag_catalog.agtype_access_operator(properties, '"revoked"'));

CREATE UNIQUE INDEX IF NOT EXISTS api_key_id_unique ON imbi."APIKey" (ag_catalog.agtype_access_operator(properties, '"key_id"'));

CREATE UNIQUE INDEX IF NOT EXISTS blueprint_name_type_unique ON imbi."Blueprint" (ag_catalog.agtype_access_operator(properties, '"name"'), ag_catalog.agtype_access_operator(properties, '"type"'));

CREATE UNIQUE INDEX IF NOT EXISTS client_credential_client_id_unique ON imbi."ClientCredential" (ag_catalog.agtype_access_operator(properties, '"client_id"'));

CREATE UNIQUE INDEX IF NOT EXISTS conversation_id_unique ON imbi."Conversation" (ag_catalog.agtype_access_operator(properties, '"id"'));

CREATE INDEX IF NOT EXISTS conversation_updated_at_idx ON imbi."Conversation" (ag_catalog.agtype_access_operator(properties, '"updated_at"'));

CREATE INDEX IF NOT EXISTS conversation_user_email_idx ON imbi."Conversation" (ag_catalog.agtype_access_operator(properties, '"user_email"'));

CREATE UNIQUE INDEX IF NOT EXISTS link_definition_slug_unique ON imbi."LinkDefinition" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE UNIQUE INDEX IF NOT EXISTS message_id_unique ON imbi."Message" (ag_catalog.agtype_access_operator(properties, '"id"'));

CREATE INDEX IF NOT EXISTS message_conversation_id_idx ON imbi."Message" (ag_catalog.agtype_access_operator(properties, '"conversation_id"'));

CREATE INDEX IF NOT EXISTS oauth_identity_email_idx ON imbi."OAuthIdentity" (ag_catalog.agtype_access_operator(properties, '"email"'));

CREATE UNIQUE INDEX IF NOT EXISTS oauth_identity_provider_user_unique ON imbi."OAuthIdentity" (ag_catalog.agtype_access_operator(properties, '"provider"'), ag_catalog.agtype_access_operator(properties, '"provider_user_id"'));

CREATE UNIQUE INDEX IF NOT EXISTS permission_name_unique ON imbi."Permission" (ag_catalog.agtype_access_operator(properties, '"name"'));

CREATE INDEX IF NOT EXISTS permission_resource_idx ON imbi."Permission" (ag_catalog.agtype_access_operator(properties, '"resource_type"'));

CREATE UNIQUE INDEX IF NOT EXISTS project_id_unique ON imbi."Project" (ag_catalog.agtype_access_operator(properties, '"id"'));

CREATE INDEX IF NOT EXISTS project_name_idx ON imbi."Project" (ag_catalog.agtype_access_operator(properties, '"name"'));

CREATE INDEX IF NOT EXISTS project_slug_idx ON imbi."Project" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE INDEX IF NOT EXISTS role_priority_idx ON imbi."Role" (ag_catalog.agtype_access_operator(properties, '"priority"'));

CREATE UNIQUE INDEX IF NOT EXISTS role_slug_unique ON imbi."Role" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE INDEX IF NOT EXISTS service_app_slug_idx ON imbi."ServiceApplication" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE INDEX IF NOT EXISTS service_app_status_idx ON imbi."ServiceApplication" (ag_catalog.agtype_access_operator(properties, '"status"'));

CREATE UNIQUE INDEX IF NOT EXISTS service_account_slug_unique ON imbi."ServiceAccount" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE UNIQUE INDEX IF NOT EXISTS session_id_unique ON imbi."Session" (ag_catalog.agtype_access_operator(properties, '"session_id"'));

CREATE INDEX IF NOT EXISTS session_expires_idx ON imbi."Session" (ag_catalog.agtype_access_operator(properties, '"expires_at"'));

CREATE UNIQUE INDEX IF NOT EXISTS team_slug_unique ON imbi."Team" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE INDEX IF NOT EXISTS third_party_service_status_idx ON imbi."ThirdPartyService" (ag_catalog.agtype_access_operator(properties, '"status"'));

CREATE UNIQUE INDEX IF NOT EXISTS third_party_service_slug_unique ON imbi."ThirdPartyService" (ag_catalog.agtype_access_operator(properties, '"slug"'));

CREATE UNIQUE INDEX IF NOT EXISTS token_jti_unique ON imbi."TokenMetadata" (ag_catalog.agtype_access_operator(properties, '"jti"'));

CREATE UNIQUE INDEX IF NOT EXISTS upload_id_unique ON imbi."Upload" (ag_catalog.agtype_access_operator(properties, '"id"'));

CREATE UNIQUE INDEX IF NOT EXISTS user_email_unique ON imbi."User" (ag_catalog.agtype_access_operator(properties, '"email"'));

CREATE INDEX IF NOT EXISTS user_active_idx ON imbi."User" (ag_catalog.agtype_access_operator(properties, '"is_active"'));
