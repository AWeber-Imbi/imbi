import type { SearchResult } from '@/api/search'

// Maps a node label to its /admin section. These node types are edited on
// the admin pages, which route by slug (see Admin.tsx).
const ADMIN_SECTIONS: Record<string, string> = {
  Blueprint: 'blueprints',
  DocumentTemplate: 'document-templates',
  Environment: 'environments',
  LinkDefinition: 'link-definitions',
  Organization: 'organizations',
  ProjectType: 'project-types',
  Role: 'roles',
  Team: 'teams',
}

export function getResultPath(result: SearchResult): null | string {
  const { node_id, node_label, project_id, slug } = result
  if (node_label === 'Project') return `/projects/${node_id}`
  // Documents and Releases live under their parent project; project_id is
  // supplied by the search API's result enrichment.
  if (node_label === 'Document')
    return project_id ? `/projects/${project_id}/documents/${node_id}` : null
  // ReleasesTab does not yet consume the subId, so this lands on the tab.
  if (node_label === 'Release')
    return project_id ? `/projects/${project_id}/releases/${node_id}` : null
  const section = ADMIN_SECTIONS[node_label]
  return section && slug ? `/admin/${section}/${slug}` : null
}
