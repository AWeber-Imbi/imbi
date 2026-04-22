import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { getProjectRelationships } from '@/api/endpoints'
import { buildRelationshipEdges } from '@/lib/relationship-edges'
import {
  LazyProjectsGraphCanvas,
  type GraphProject,
} from '@/components/LazyProjectsGraphCanvas'
import { EditRelationshipsDialog } from '@/components/EditRelationshipsDialog'
import type { Project, ProjectRelationship } from '@/types'

type RelFilter = 'all' | 'uses' | 'used-by'

export function ProjectRelationshipsTab({
  orgSlug,
  projectId,
  project,
}: {
  orgSlug: string
  projectId: string
  project: Project
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['project-relationships', orgSlug, projectId],
    queryFn: () => getProjectRelationships(orgSlug, projectId),
  })
  const [filter, setFilter] = useState<RelFilter>('all')
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  const sub = 'text-tertiary'

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <p className={sub}>Loading relationships…</p>
        </CardContent>
      </Card>
    )
  }
  if (isError && !data) {
    return (
      <Card>
        <CardContent>
          <p className={sub}>Failed to load relationships.</p>
        </CardContent>
      </Card>
    )
  }

  const rels = data?.relationships ?? []

  const outbound = rels.filter((r) => r.direction === 'outbound')
  const inbound = rels.filter((r) => r.direction === 'inbound')
  const outboundVisible = filter !== 'used-by'
  const inboundVisible = filter !== 'uses'
  const visibleOutbound = outboundVisible ? outbound : []
  const visibleInbound = inboundVisible ? inbound : []

  // Build projects and edges for the shared canvas, filtered by visibility.
  // Deduplicate: a related project can appear in both inbound and outbound.
  const visibleRels = [...visibleOutbound, ...visibleInbound]
  const projects: GraphProject[] = Array.from(
    new Map<string, GraphProject>([
      [
        project.id,
        {
          id: project.id,
          name: project.name,
          project_types: project.project_types?.map((pt) => ({
            slug: pt.slug,
            icon: pt.icon ?? null,
          })),
        },
      ],
      ...visibleRels.map(
        (r) =>
          [
            r.project.id,
            {
              id: r.project.id,
              name: r.project.name,
              project_types: r.project.project_type
                ? [
                    {
                      slug: r.project.project_type,
                      icon: r.project.project_type_icon ?? null,
                    },
                  ]
                : [],
            },
          ] as [string, GraphProject],
      ),
    ]).values(),
  )

  const edges = Array.from(
    new Map(
      buildRelationshipEdges(projectId, visibleRels).map((edge) => [
        edge.id,
        edge,
      ]),
    ).values(),
  )

  return (
    <>
      {rels.length === 0 ? (
        <Card>
          <CardContent className="flex items-center justify-between">
            <p className={sub}>This project has no relationships.</p>
            <Button
              size="sm"
              className="gap-1 bg-action text-action-foreground hover:bg-action-hover"
              onClick={() => setEditDialogOpen(true)}
            >
              Edit
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div
          className="grid min-h-[24rem] grid-cols-1 gap-6 lg:grid-cols-[400px_1fr]"
          style={{
            height: 'calc(100vh - 22rem - var(--assistant-height, 4rem))',
          }}
        >
          <ProjectRelationshipsSidebar
            outbound={outbound}
            inbound={inbound}
            outboundVisible={outboundVisible}
            inboundVisible={inboundVisible}
            filter={filter}
            onFilterChange={setFilter}
            onAdd={() => setEditDialogOpen(true)}
          />
          <LazyProjectsGraphCanvas
            projects={projects}
            edges={edges}
            centerId={projectId}
          />
        </div>
      )}
      <EditRelationshipsDialog
        isOpen={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        projectId={projectId}
        projectName={project.name}
        relationships={rels}
      />
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                           */
/* ------------------------------------------------------------------ */

interface RelationshipsSidebarProps {
  outbound: ProjectRelationship[]
  inbound: ProjectRelationship[]
  outboundVisible: boolean
  inboundVisible: boolean
  filter: RelFilter
  onFilterChange: (f: RelFilter) => void
  onAdd: () => void
}

export function ProjectRelationshipsSidebar({
  outbound,
  inbound,
  outboundVisible,
  inboundVisible,
  filter,
  onFilterChange,
  onAdd,
}: RelationshipsSidebarProps) {
  const sectionLabel = 'text-tertiary'
  const sub = 'text-tertiary'

  const chipBase =
    'rounded-full px-3 py-1 text-xs font-medium transition-colors'
  const chipSelected = 'bg-amber-500 text-white'
  const chipUnselected =
    'border border-input text-secondary hover:border-secondary'

  return (
    <Card
      className={`h-full min-h-0 w-full flex-shrink-0 overflow-y-auto ${''}`}
    >
      <CardHeader className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-1.5">
            {(['all', 'uses', 'used-by'] as const).map((f) => (
              <Button
                key={f}
                type="button"
                variant="ghost"
                aria-pressed={filter === f}
                onClick={() => onFilterChange(f)}
                className={`h-auto ${chipBase} ${filter === f ? chipSelected : chipUnselected}`}
              >
                {f === 'all' ? 'All' : f === 'uses' ? 'Uses' : 'Used by'}
              </Button>
            ))}
          </div>
          <Button variant="ghost" size="sm" onClick={onAdd}>
            Edit
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-4 pt-2">
        {/* Outbound (USES) section */}
        {outboundVisible && (
          <div className="mb-4">
            <h4
              className={`mb-2 text-[10px] font-medium uppercase tracking-[0.12em] ${sectionLabel}`}
            >
              Uses
            </h4>
            {outbound.length === 0 ? (
              <p className={`text-xs ${sub}`}>None</p>
            ) : (
              <ul className="space-y-1">
                {outbound.map((r, i) => (
                  <SidebarProjectRow key={`out:${r.project.id}:${i}`} rel={r} />
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Inbound (USED BY) section */}
        {inboundVisible && (
          <div>
            <h4
              className={`mb-2 text-[10px] font-medium uppercase tracking-[0.12em] ${sectionLabel}`}
            >
              Used by
            </h4>
            {inbound.length === 0 ? (
              <p className={`text-xs ${sub}`}>None</p>
            ) : (
              <ul className="space-y-1">
                {inbound.map((r, i) => (
                  <SidebarProjectRow key={`in:${r.project.id}:${i}`} rel={r} />
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SidebarProjectRow({ rel }: { rel: ProjectRelationship }) {
  const typeSlug = rel.project.project_type ?? ''
  const muted = 'text-tertiary'

  return (
    <li className="flex items-center gap-2 py-1">
      <Link
        to={`/projects/${rel.project.id}`}
        className="truncate text-sm text-warning hover:underline"
      >
        {rel.project.name}
      </Link>
      {typeSlug && (
        <span className={`flex-shrink-0 text-[10px] ${muted}`}>{typeSlug}</span>
      )}
    </li>
  )
}
