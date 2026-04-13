import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { getProjectRelationships } from '@/api/endpoints'
import { ProjectsGraphCanvas } from '@/components/ProjectsGraphCanvas'
import {
  buildRelationshipEdges,
  type GraphEdge,
} from '@/lib/relationship-edges'
import type { Project } from '@/types'

interface ProjectGraphViewProps {
  projects: Project[]
  isDarkMode: boolean
}

export function ProjectGraphView({
  projects,
  isDarkMode,
}: ProjectGraphViewProps) {
  // Map project ID → node ID for edge resolution.
  const idToNodeId = useMemo(() => {
    const map = new Map<string, string>()
    projects.forEach((p) => {
      map.set(p.id, p.id)
    })
    return map
  }, [projects])

  const relationshipQueries = useQueries({
    queries: projects.map((p) => {
      const orgSlug = p.team?.organization?.slug ?? ''
      return {
        queryKey: ['project-relationships', orgSlug, p.id],
        queryFn: () => getProjectRelationships(orgSlug, p.id),
        enabled: Boolean(orgSlug && p.id),
      }
    }),
  })

  const relationshipsData = useMemo(
    () => relationshipQueries.map((q) => q.data),
    // Depend on each individual .data — React Query keeps these
    // references stable across renders when the payload is unchanged.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    relationshipQueries.map((q) => q.data),
  )

  const edges = useMemo(() => {
    const seen = new Set<string>()
    const result: GraphEdge[] = []
    projects.forEach((p, index) => {
      const response = relationshipsData[index]
      if (!response) return
      for (const edge of buildRelationshipEdges(p.id, response.relationships)) {
        if (edge.source !== p.id) continue
        if (!idToNodeId.get(edge.target)) continue
        if (seen.has(edge.id)) continue
        seen.add(edge.id)
        result.push(edge)
      }
    })
    return result
  }, [projects, idToNodeId, relationshipsData])

  return (
    <ProjectsGraphCanvas
      projects={projects}
      edges={edges}
      isDarkMode={isDarkMode}
    />
  )
}
