import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getProjectRelationships } from '@/api/endpoints'
import { EditRelationshipsDialog } from '@/components/EditRelationshipsDialog'
import {
  type GraphProject,
  LazyProjectsGraphCanvas,
} from '@/components/LazyProjectsGraphCanvas'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { buildRelationshipEdges } from '@/lib/relationship-edges'
import type { Project, ProjectRelationship } from '@/types'

interface RelationshipsSidebarProps {
  filter: RelFilter
  inbound: ProjectRelationship[]
  inboundVisible: boolean
  onAdd: () => void
  onFilterChange: (f: RelFilter) => void
  outbound: ProjectRelationship[]
  outboundVisible: boolean
}

type RelFilter = 'all' | 'used-by' | 'uses'

/* ------------------------------------------------------------------ */
/*  Sidebar                                                           */
/* ------------------------------------------------------------------ */

export function ProjectRelationshipsTab({
  orgSlug,
  project,
  projectId,
}: {
  orgSlug: string
  project: Project
  projectId: string
}) {
  const { data, isError, isLoading } = useQuery({
    queryFn: ({ signal }) =>
      getProjectRelationships(orgSlug, projectId, signal),
    queryKey: ['project-relationships', orgSlug, projectId],
  })
  const [filter, setFilter] = useState<RelFilter>('all')
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  const sub = 'text-tertiary'

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-4">
          <p className={sub}>Loading relationships…</p>
        </CardContent>
      </Card>
    )
  }
  if (isError && !data) {
    return (
      <Card>
        <CardContent className="p-4">
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
            icon: pt.icon ?? null,
            slug: pt.slug,
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
                      icon: r.project.project_type_icon ?? null,
                      slug: r.project.project_type,
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
          <CardContent className="flex items-center justify-between p-4">
            <p className={sub}>This project has no relationships.</p>
            <Button
              onClick={() => setEditDialogOpen(true)}
              size="sm"
              variant="outline"
            >
              Edit
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div
          className="grid min-h-96 grid-cols-1 gap-6 lg:grid-cols-[400px_1fr]"
          style={{
            height: 'calc(100vh - 22rem - var(--assistant-height, 4rem))',
          }}
        >
          <ProjectRelationshipsSidebar
            filter={filter}
            inbound={inbound}
            inboundVisible={inboundVisible}
            onAdd={() => setEditDialogOpen(true)}
            onFilterChange={setFilter}
            outbound={outbound}
            outboundVisible={outboundVisible}
          />
          <LazyProjectsGraphCanvas
            centerId={projectId}
            edges={edges}
            projects={projects}
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

function ProjectRelationshipsSidebar({
  filter,
  inbound,
  inboundVisible,
  onAdd,
  onFilterChange,
  outbound,
  outboundVisible,
}: RelationshipsSidebarProps) {
  const sectionLabel = 'text-tertiary'
  const sub = 'text-tertiary'

  const chipBase =
    'rounded-full px-3 py-1 text-xs font-medium transition-colors'
  const chipSelected = 'bg-amber-500 text-white'
  const chipUnselected =
    'border border-input text-secondary hover:border-secondary'

  return (
    <Card className={`size-full min-h-0 shrink-0 overflow-y-auto ${''}`}>
      <CardHeader className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-1.5">
            {(['all', 'uses', 'used-by'] as const).map((f) => (
              <Button
                aria-pressed={filter === f}
                className={`h-auto ${chipBase} ${filter === f ? chipSelected : chipUnselected}`}
                key={f}
                onClick={() => onFilterChange(f)}
                type="button"
                variant="ghost"
              >
                {f === 'all' ? 'All' : f === 'uses' ? 'Uses' : 'Used by'}
              </Button>
            ))}
          </div>
          <Button onClick={onAdd} size="sm" variant="ghost">
            Edit
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-4 pt-2">
        {/* Outbound (USES) section */}
        {outboundVisible && (
          <div className="mb-4">
            <h4
              className={`mb-2 text-[10px] font-medium tracking-[0.12em] uppercase ${sectionLabel}`}
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
              className={`mb-2 text-[10px] font-medium tracking-[0.12em] uppercase ${sectionLabel}`}
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
        className="text-warning truncate text-sm hover:underline"
        to={`/projects/${rel.project.id}`}
      >
        {rel.project.name}
      </Link>
      {typeSlug && (
        <span className={`shrink-0 text-[10px] ${muted}`}>{typeSlug}</span>
      )}
    </li>
  )
}
