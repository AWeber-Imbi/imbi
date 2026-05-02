import { useMemo, useState } from 'react'

import { useNavigate, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { Grid3x3, List, Network, Plus, Search } from 'lucide-react'

import { getProjects } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { sortEnvironments } from '@/lib/utils'

import { NewProjectDialog } from './NewProjectDialog'
import { ProjectGraphView } from './ProjectGraphView'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { EnvironmentBadge } from './ui/environment-badge'
import { Input } from './ui/input'
import { ScoreBadge } from './ui/score-badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './ui/table'

export function ProjectsView() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const rawView = searchParams.get('view')
  const viewMode: 'graph' | 'grid' | 'list' =
    rawView === 'grid' || rawView === 'list' || rawView === 'graph'
      ? rawView
      : 'grid'
  const searchQuery = searchParams.get('q') ?? ''

  const setViewMode = (v: 'graph' | 'grid' | 'list') =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('view', v)
        return next
      },
      { replace: true },
    )

  const setSearchQuery = (q: string) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (q) next.set('q', q)
        else next.delete('q')
        return next
      },
      { replace: true },
    )

  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)

  const { data: projects, isLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  const handleProjectSelect = (projectId: string) => {
    navigate(`/projects/${projectId}`)
  }

  const filteredProjects = useMemo(() => {
    const all = projects || []
    if (!searchQuery) return all
    const query = searchQuery.toLowerCase()
    return all.filter((p) => {
      return (
        p.name.toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.team.name.toLowerCase().includes(query) ||
        (p.project_types || []).some((pt) =>
          pt.name.toLowerCase().includes(query),
        )
      )
    })
  }, [projects, searchQuery])

  if (isLoading) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div className="flex h-64 items-center justify-center">
          <div className="text-lg">Loading projects...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-primary">Projects</h1>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={() => setNewProjectDialogOpen(true)}
            size="sm"
          >
            <Plus className="mr-2 h-4 w-4" />
            New Project
          </Button>
        </div>

        {/* Search and Filters */}
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <div className="relative max-w-md flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
              <Input
                className={`pl-9 ${''}`}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search projects..."
                type="text"
                value={searchQuery}
              />
            </div>

            <div className="flex items-center rounded-lg border border-secondary">
              <Button
                aria-label="Grid view"
                className={`rounded-r-none ${viewMode === 'grid' ? 'bg-amber-bg text-amber-text' : ''}`}
                onClick={() => setViewMode('grid')}
                size="sm"
                variant="ghost"
              >
                <Grid3x3 className="h-4 w-4" />
              </Button>
              <Button
                aria-label="List view"
                className={`rounded-none ${viewMode === 'list' ? 'bg-amber-bg text-amber-text' : ''}`}
                onClick={() => setViewMode('list')}
                size="sm"
                variant="ghost"
              >
                <List className="h-4 w-4" />
              </Button>
              <Button
                aria-label="Graph view"
                className={`rounded-l-none ${viewMode === 'graph' ? 'bg-amber-bg text-amber-text' : ''}`}
                onClick={() => setViewMode('graph')}
                size="sm"
                variant="ghost"
              >
                <Network className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </Card>
      </div>

      {/* Projects Graph/Grid/List */}
      {viewMode === 'graph' ? (
        <ProjectGraphView projects={filteredProjects} />
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProjects.map((project) => {
            return (
              <Card
                className={`cursor-pointer p-5 transition-shadow hover:shadow-md ${''}`}
                key={`card-${project.id}`}
                onClick={() => handleProjectSelect(project.id)}
              >
                <div className="mb-3 flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <h3 className="mb-1 truncate font-medium text-primary">
                      {project.name}
                    </h3>
                    <p className="text-sm text-tertiary">
                      {(project.project_types || [])
                        .map((pt) => pt.name)
                        .join(', ')}
                    </p>
                  </div>
                  <div className="ml-3">
                    <ScoreBadge
                      score={project.score}
                      size="md"
                      variant="circle"
                    />
                  </div>
                </div>

                {project.description && (
                  <p className="mb-3 line-clamp-2 text-sm text-secondary">
                    {project.description}
                  </p>
                )}

                <div className="mb-3">
                  <p className="text-xs text-tertiary">{project.team.name}</p>
                </div>

                {project.environments && project.environments.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    {sortEnvironments(project.environments || []).map((env) => (
                      <EnvironmentBadge
                        key={env.slug}
                        label_color={env.label_color}
                        name={env.name}
                        slug={env.slug}
                      />
                    ))}
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader className="border-b border-tertiary bg-secondary">
                <TableRow>
                  <TableHead
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Project
                  </TableHead>
                  <TableHead
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Type
                  </TableHead>
                  <TableHead
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Team
                  </TableHead>
                  <TableHead
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Environments
                  </TableHead>
                  <TableHead
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Health
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="divide-y divide-tertiary">
                {filteredProjects.map((project) => {
                  return (
                    <TableRow
                      className="cursor-pointer transition-colors hover:bg-secondary"
                      key={`table-${project.id}`}
                      onClick={() => handleProjectSelect(project.id)}
                    >
                      <TableCell className="px-6 py-4 font-medium text-primary">
                        {project.name}
                      </TableCell>
                      <TableCell className="px-6 py-4 text-secondary">
                        {(project.project_types || [])
                          .map((pt) => pt.name)
                          .join(', ')}
                      </TableCell>
                      <TableCell className="px-6 py-4 text-secondary">
                        {project.team.name}
                      </TableCell>
                      <TableCell className="px-6 py-4">
                        {project.environments &&
                          project.environments.length > 0 && (
                            <div className="flex flex-wrap items-center gap-2">
                              {sortEnvironments(project.environments || []).map(
                                (env) => (
                                  <EnvironmentBadge
                                    key={env.slug}
                                    label_color={env.label_color}
                                    name={env.name}
                                    slug={env.slug}
                                  />
                                ),
                              )}
                            </div>
                          )}
                      </TableCell>
                      <TableCell className="px-6 py-4">
                        <ScoreBadge score={project.score} variant="circle" />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </Card>
      )}

      {filteredProjects.length === 0 && viewMode !== 'graph' && (
        <div className="py-12 text-center">
          <p className="text-tertiary">
            No projects found matching your criteria
          </p>
        </div>
      )}

      <NewProjectDialog
        isOpen={newProjectDialogOpen}
        onClose={() => setNewProjectDialogOpen(false)}
        onProjectCreated={(id) => navigate(`/projects/${id}`)}
      />
    </div>
  )
}
