import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { getProjectRelationships } from '@/api/endpoints'
import { ProjectsGraphCanvas } from '@/components/ProjectsGraphCanvas'
import { Card } from '@/components/ui/card'
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

  const isAnyLoading = relationshipQueries.some((q) => q.isLoading)
  const failedQueries = relationshipQueries.filter((q) => q.isError)

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

  const sub = isDarkMode ? 'text-gray-400' : 'text-slate-500'
  const cardClass = `flex items-center justify-center p-12 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`

  if (isAnyLoading) {
    return (
      <Card className={cardClass}>
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent opacity-50" />
          <p className={`text-sm ${sub}`}>Loading relationships…</p>
        </div>
      </Card>
    )
  }

  if (failedQueries.length > 0) {
    return (
      <Card className={cardClass}>
        <p className={`text-sm ${sub}`}>
          Failed to load relationships for {failedQueries.length} project
          {failedQueries.length === 1 ? '' : 's'}.
        </p>
      </Card>
    )
  }

  return (
    <ProjectsGraphCanvas
      projects={projects}
      edges={edges}
      isDarkMode={isDarkMode}
    />
  )
}
