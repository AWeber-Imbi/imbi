import type { ProjectRelationship } from '@/types'

export interface GraphEdge {
  id: string
  source: string
  target: string
  label: string
}

/**
 * Build graph edges from a project's relationships.
 * Direction is preserved: outbound edges point from the project to its
 * dependencies; inbound edges point from dependents to the project.
 */
export function buildRelationshipEdges(
  projectId: string,
  relationships: ProjectRelationship[],
): GraphEdge[] {
  return relationships.map((r) => {
    const source = r.direction === 'outbound' ? projectId : r.project.id
    const target = r.direction === 'outbound' ? r.project.id : projectId
    return {
      id: `${source}->${target}`,
      source,
      target,
      label: 'depends on',
    }
  })
}
