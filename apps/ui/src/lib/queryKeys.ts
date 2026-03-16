/**
 * Map resource names (from the assistant's refresh_data tool)
 * to React Query keys for cache invalidation.
 */
export function getQueryKeysForResource(
  resource: string,
  orgSlug?: string,
): string[][] {
  switch (resource) {
    case 'projects':
      return [['projects']]
    case 'project_types':
      return orgSlug
        ? [['projectTypes', orgSlug]]
        : [['projectTypes']]
    case 'environments':
      return orgSlug
        ? [['environments', orgSlug]]
        : [['environments']]
    case 'teams':
      return orgSlug ? [['teams', orgSlug]] : [['teams']]
    case 'organizations':
      return [['organizations']]
    case 'blueprints':
      return [
        ['blueprints'],
        ['blueprint'],
        ['openapi-spec'],
        ['teamSchema'],
        ['environmentSchema'],
        ['projectTypeSchema'],
      ]
    case 'roles':
      return [['roles'], ['role']]
    case 'users':
      return [['adminUsers']]
    case 'service_accounts':
      return [['serviceAccounts']]
    default:
      return []
  }
}
