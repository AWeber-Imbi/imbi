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
      return orgSlug ? [['projectTypes', orgSlug]] : [['projectTypes']]
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
