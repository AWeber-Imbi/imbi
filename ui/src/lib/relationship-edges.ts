import type { ProjectRelationship } from '@/types'

export interface GraphEdge {
  arrowPlacement?: 'end' | 'mid' | 'none'
  fill?: string
  id: string
  label: string
  source: string
  target: string
}

/** Orange for "depends on" (outbound), blue for "depended upon" (inbound). */
export const EDGE_COLOR_DEPENDS_ON = '#f59e0b'
export const EDGE_COLOR_DEPENDED_UPON = '#3b82f6'

/**
 * Build graph edges from a project's relationships.
 * Direction is preserved: outbound edges point from the project to its
 * dependencies; inbound edges point from dependents to the project.
 * Edge color indicates the relationship type from the center project's
 * perspective: orange = "depends on", blue = "depended upon".
 */
export function buildRelationshipEdges(
  projectId: string,
  relationships: ProjectRelationship[],
): GraphEdge[] {
  return relationships.map((r) => {
    const isOutbound = r.direction === 'outbound'
    const source = isOutbound ? projectId : r.project.id
    const target = isOutbound ? r.project.id : projectId
    return {
      arrowPlacement: 'end',
      fill: isOutbound ? EDGE_COLOR_DEPENDS_ON : EDGE_COLOR_DEPENDED_UPON,
      id: `${source}->${target}`,
      label: isOutbound ? 'depends on' : 'depended upon',
      source,
      target,
    }
  })
}
