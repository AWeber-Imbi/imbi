import { useQueries, useQuery } from '@tanstack/react-query'

import {
  getProject,
  listBlueprints,
  listDocumentTemplates,
  listEnvironments,
  listTags,
  listTeams,
} from '@/api/endpoints'
import type { SearchResult } from '@/api/search'

export interface EnrichedInfo {
  breadcrumb?: string
  name?: string
}

// fallow-ignore-next-line complexity
export function useSearchEnrichment(
  results: SearchResult[],
  orgSlug: null | string,
): Map<string, EnrichedInfo> {
  const uniqueProjectIds = [
    ...new Set(
      results.filter((r) => r.node_label === 'Project').map((r) => r.node_id),
    ),
  ]

  const hasLabel = (label: string) =>
    results.some((r) => r.node_label === label)

  const projectQueries = useQueries({
    queries: orgSlug
      ? uniqueProjectIds.map((id) => ({
          queryFn: ({ signal }: { signal: AbortSignal }) =>
            getProject(orgSlug, id, signal),
          queryKey: ['project', orgSlug, id],
          staleTime: 60_000,
        }))
      : [],
  })

  const teamsQuery = useQuery({
    enabled: !!orgSlug && hasLabel('Team'),
    queryFn: ({ signal }) => listTeams(orgSlug!, signal),
    queryKey: ['teams', orgSlug],
    staleTime: 60_000,
  })

  const environmentsQuery = useQuery({
    enabled: !!orgSlug && hasLabel('Environment'),
    queryFn: ({ signal }) => listEnvironments(orgSlug!, signal),
    queryKey: ['environments', orgSlug],
    staleTime: 60_000,
  })

  const blueprintsQuery = useQuery({
    enabled: hasLabel('Blueprint'),
    queryFn: ({ signal }) => listBlueprints(undefined, signal),
    queryKey: ['blueprints'],
    staleTime: 60_000,
  })

  const tagsQuery = useQuery({
    enabled: !!orgSlug && hasLabel('Tag'),
    queryFn: ({ signal }) => listTags(orgSlug!, signal),
    queryKey: ['tags', orgSlug],
    staleTime: 60_000,
  })

  const docTemplatesQuery = useQuery({
    enabled: !!orgSlug && hasLabel('DocumentTemplate'),
    queryFn: ({ signal }) => listDocumentTemplates(orgSlug!, signal),
    queryKey: ['document-templates', orgSlug],
    staleTime: 60_000,
  })

  const map = new Map<string, EnrichedInfo>()

  for (const q of projectQueries) {
    if (q.data) {
      const p = q.data
      map.set(p.id, {
        breadcrumb: projectBreadcrumb(p),
        name: p.name,
      })
    }
  }

  for (const team of teamsQuery.data ?? []) {
    if (team.id) {
      map.set(team.id, {
        breadcrumb: `${team.organization.name} › Teams`,
        name: team.name,
      })
    }
  }

  for (const env of environmentsQuery.data ?? []) {
    if (env.id) {
      map.set(env.id, { name: env.name })
    }
  }

  for (const bp of blueprintsQuery.data ?? []) {
    if (bp.id) {
      map.set(bp.id, { name: bp.name })
    }
  }

  for (const tag of tagsQuery.data ?? []) {
    map.set(tag.id, {
      breadcrumb: `${tag.organization.name} › Tags`,
      name: tag.name,
    })
  }

  for (const dt of docTemplatesQuery.data ?? []) {
    map.set(dt.id, {
      breadcrumb: `${dt.organization.name} › Doc Templates`,
      name: dt.name,
    })
  }

  return map
}

// fallow-ignore-next-line complexity
function projectBreadcrumb(p: {
  project_type?: null | { name: string }
  project_types?: { name: string }[]
  team: { name: string }
}): string {
  const ptName = p.project_types?.[0]?.name ?? p.project_type?.name
  return ptName ? `${ptName} › ${p.team.name}` : p.team.name
}
