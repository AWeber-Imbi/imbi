import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { getProjectRelationships } from '@/api/endpoints'
import { LazyProjectsGraphCanvas } from '@/components/LazyProjectsGraphCanvas'
import { Card } from '@/components/ui/card'
import {
  buildRelationshipEdges,
  type GraphEdge,
} from '@/lib/relationship-edges'
import type { Project } from '@/types'

interface ProjectGraphViewProps {
  projects: Project[]
}

export function ProjectGraphView({ projects }: ProjectGraphViewProps) {
  // Set of project IDs for edge target existence checks.
  const idSet = useMemo(() => new Set(projects.map((p) => p.id)), [projects])

  const relationshipQueries = useQueries({
    queries: projects.map((p) => {
      const orgSlug = p.team?.organization?.slug ?? ''
      return {
        queryKey: ['project-relationships', orgSlug, p.id],
        queryFn: ({ signal }) => getProjectRelationships(orgSlug, p.id, signal),
        enabled: Boolean(orgSlug && p.id),
      }
    }),
  })

  const isAnyLoading = relationshipQueries.some((q) => q.isLoading)
  const failedQueries = relationshipQueries.filter((q) => q.isError && !q.data)

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
        if (!idSet.has(edge.target)) continue
        if (seen.has(edge.id)) continue
        seen.add(edge.id)
        result.push(edge)
      }
    })
    return result
  }, [projects, idSet, relationshipsData])

  const sub = 'text-tertiary'
  const cardClass = 'flex items-center justify-center p-12'

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
    <div
      style={{
        height: 'calc(100vh - 280px - var(--assistant-height, 64px))',
      }}
    >
      <LazyProjectsGraphCanvas projects={projects} edges={edges} />
    </div>
  )
}
