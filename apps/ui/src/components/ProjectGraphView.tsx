import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { getProjectRelationships } from '@/api/endpoints'
import { ProjectsGraphCanvas } from '@/components/ProjectsGraphCanvas'
import type { Project, ProjectRelationshipsResponse } from '@/types'
import type { GraphEdge } from 'reagraph'

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

  // Fetch relationships for every visible project in parallel. Each query is
  // cached by ['project-relationships', orgSlug, projectId] and reuses data
  // from the ProjectDetail tab when the user crosses between views.
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

  // Extract the underlying data array. React Query keeps .data referentially
  // stable across renders when the payload is unchanged, so depending on
  // relationshipsData keeps the useMemo from re-running on every render.
  const relationshipsData = relationshipQueries.map((q) => q.data)

  const edges: GraphEdge[] = useMemo(() => {
    const seen = new Set<string>()
    const result: GraphEdge[] = []

    projects.forEach((p, index) => {
      const response = relationshipsData[index] as
        | ProjectRelationshipsResponse
        | undefined
      if (!response) return
      const sourceId = p.id
      for (const rel of response.relationships) {
        // Only render OUTBOUND edges from each node's perspective — inbound
        // edges from other projects will show up when we iterate those
        // projects' outbound lists, so rendering both would double-count.
        if (rel.direction !== 'outbound') continue
        const targetId = idToNodeId.get(rel.project.id)
        if (!targetId) continue
        const edgeId = `${sourceId}->${targetId}`
        if (seen.has(edgeId)) continue
        seen.add(edgeId)
        result.push({
          id: edgeId,
          source: sourceId,
          target: targetId,
          label: 'depends on',
        })
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
