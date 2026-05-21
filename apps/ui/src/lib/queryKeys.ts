/**
 * Centralized React Query keys for plugin-related queries.
 *
 * Inline construction drifts: a typo in one invalidate site silently
 * breaks the other.  Use these builders instead of literals.
 */
export const queryKeys = {
  adminAuthProviders: () => ['admin', 'auth-providers'] as const,
  adminLocalAuth: () => ['admin', 'local-auth'] as const,
  adminPlugin: (slug: string) => ['admin-plugin', slug] as const,
  adminPlugins: () => ['admin-plugins'] as const,
  anchorEdges: (
    kind: string,
    orgSlug: string,
    anchorSlug: string,
    relType: string,
  ) => ['anchor-edges', kind, orgSlug, anchorSlug, relType] as const,
  environments: (orgSlug: string) => ['environments', orgSlug] as const,
  identityPlugins: (orgSlug: string) => ['identity-plugins', orgSlug] as const,
  pluginEdgesByOrg: (pluginSlug: string, relType: string, orgSlug: string) =>
    ['plugin-edges-by-org', pluginSlug, relType, orgSlug] as const,
  pluginEntities: (slug: string, label: string) =>
    ['plugin-entities', slug, label] as const,
  pluginEntitySchema: (slug: string, label: string) =>
    ['plugin-entity-schema', slug, label] as const,
  projectTypes: (orgSlug: string) => ['projectTypes', orgSlug] as const,
  // Login form's view of providers (/auth/providers, public payload with
  // default_redirect). Distinct from adminAuthProviders, which lists admin
  // metadata from /admin/auth-providers — different endpoint, different shape,
  // different consumers. Mutations on the admin list must invalidate both so
  // the LoginPage picker stays in sync.
  publicAuthProviders: () => ['authProviders'] as const,
  teams: (orgSlug: string) => ['teams', orgSlug] as const,
} as const

/**
 * Map resource names (from the assistant's refresh_data tool)
 * to React Query keys for cache invalidation.
 */
export function getQueryKeysForResource(
  resource: string,
  orgSlug?: string,
): string[][] {
  switch (resource) {
    case 'blueprints':
      return [
        ['blueprints'],
        ['blueprint'],
        ['openapi-spec'],
        ['teamSchema'],
        ['environmentSchema'],
        ['projectTypeSchema'],
      ]
    case 'environments':
      return orgSlug ? [['environments', orgSlug]] : [['environments']]
    case 'organizations':
      return [['organizations']]
    case 'project_types':
      return orgSlug
        ? [Array.from(queryKeys.projectTypes(orgSlug))]
        : [['projectTypes']]
    case 'projects':
      return [['projects']]
    case 'roles':
      return [['roles'], ['role']]
    case 'service_accounts':
      return [['serviceAccounts']]
    case 'teams':
      return orgSlug ? [['teams', orgSlug]] : [['teams']]
    case 'users':
      return [['adminUsers']]
    default:
      return []
  }
}
