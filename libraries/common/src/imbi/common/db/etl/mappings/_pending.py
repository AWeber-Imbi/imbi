"""The tables that do not have a mapping module yet, by Wave 2 agent.

The runner truncates these tables with the mapped tables, in the same
statement, and loads no rows into them. Without them, the TRUNCATE
fails: PostgreSQL does not truncate a table that an unlisted table
refers to. The runner refuses to run while this list is not empty,
unless the caller allows it (tests and rehearsals only).

When you add the mapping module of a table, delete the table from your
list here in the same commit. ``libraries/common/tests/db/etl/
test_registry.py`` fails when a table is in both places, in neither, or
here but not in ``schemata/tables/public/``. Its ``test_nothing_pending``
fails while any list has a table; it runs only with
``IMBI_ETL_REQUIRE_COMPLETE=1``, which the Wave 2 exit sets.

When your list is empty, keep your key with ``()`` and keep the comment
line above each list. The comment lines are not changed by any agent,
so the merges of two agents' deletions do not touch the same lines.
The lists follow the execution plan section 5 and the implementation
plan section 5; move a table to another agent's list if the plans
assign it there.
"""

PENDING: dict[str, tuple[str, ...]] = {
    # K tenancy (WP2.1), with the ETL mappings of roles and permissions.
    'K': (
        'environments',
        'link_definitions',
        'memberships',
        'permissions',
        'principals',
        'project_types',
        'role_grants',
        'roles',
        'service_accounts',
        'team_members',
        'teams',
        'users',
    ),
    # L projects (WP2.2).
    'L': (
        'blueprints',
        'project_dependencies',
        'project_promotions',
        'project_syncs',
        'project_type_assignments',
        'projects',
        'scoring_policies',
        'scoring_policy_targets',
    ),
    # M rbac (WP2.3), with the ETL mappings of integrations and
    # plugin_registrations.
    'M': (
        'api_keys',
        'client_credentials',
        'identity_connections',
        'integrations',
        'issued_tokens',
        'local_auth_settings',
        'oauth_clients',
        'password_reset_tokens',
        'plugin_registrations',
        'resource_acls',
        'totp_secrets',
    ),
    # N releases (WP2.4, the release part).
    'N': ('releases',),
    # O deployments (WP2.4, the deployment part).
    'O': (
        'blockers',
        'deployments',
        'project_environments',
    ),
    # P sbom (WP2.5).
    'P': (
        'advisories',
        'component_advisories',
        'component_governance',
        'component_identifiers',
        'component_notes',
        'component_overrides',
        'component_release_governance',
        'component_release_overrides',
        'component_releases',
        'components',
    ),
    # Q documents (WP2.6).
    'Q': (
        'comment_threads',
        'comments',
        'document_likes',
        'document_tags',
        'document_templates',
        'documents',
        'template_project_types',
        'template_tags',
        'uploads',
    ),
    # R integrations (WP2.7).
    'R': (
        'project_capabilities',
        'project_integrations',
        'project_type_capabilities',
        'webhook_rules',
        'webhooks',
    ),
    # S ai (WP2.8).
    'S': (
        'ai_model_teams',
        'ai_models',
        'ai_providers',
        'analysis_reports',
        'analysis_results',
        'conversations',
        'mcp_servers',
        'messages',
    ),
    # T plugins (WP2.9).
    'T': (
        'plugin_edges',
        'plugin_entities',
        'plugin_entity_keys',
    ),
    # U search (WP2.10).
    'U': ('embeddings',),
}
