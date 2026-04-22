import { Search, Plus, Grid3x3, List, Network } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Card } from './ui/card'
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getProjects } from '@/api/endpoints'
import { EnvironmentBadge } from './ui/environment-badge'
import { sortEnvironments } from '@/lib/utils'
import { useOrganization } from '@/contexts/OrganizationContext'
import { NewProjectDialog } from './NewProjectDialog'
import { ProjectGraphView } from './ProjectGraphView'

export function ProjectsView() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const rawView = searchParams.get('view')
  const viewMode: 'grid' | 'list' | 'graph' =
    rawView === 'grid' || rawView === 'list' || rawView === 'graph'
      ? rawView
      : 'grid'
  const searchQuery = searchParams.get('q') ?? ''

  const setViewMode = (v: 'grid' | 'list' | 'graph') =>
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
    queryKey: ['projects', orgSlug],
    queryFn: () => getProjects(orgSlug),
    enabled: !!orgSlug,
  })

  const getHealthColor = (health: number) => {
    if (health >= 80) return 'text-success bg-success'
    if (health >= 70) return 'text-warning bg-warning'
    return 'text-danger bg-danger'
  }

  const getHealthRingColor = (health: number) => {
    if (health >= 80) return 'ring-success'
    if (health >= 70) return 'ring-warning'
    return 'ring-danger'
  }

  // Mock health score - deterministic from slug so it's stable across renders.
  // Will come from the API in the future.
  const getMockHealth = (slug: string) => {
    let hash = 0
    for (let i = 0; i < slug.length; i++) {
      hash = ((hash << 5) - hash + slug.charCodeAt(i)) | 0
    }
    return 70 + Math.abs(hash % 30)
  }

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
            size="sm"
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={() => setNewProjectDialogOpen(true)}
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
                type="text"
                placeholder="Search projects..."
                className={`pl-9 ${''}`}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <div className="flex items-center rounded-lg border border-secondary">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setViewMode('grid')}
                className={`rounded-r-none ${viewMode === 'grid' ? 'bg-amber-bg text-amber-text' : ''}`}
                aria-label="Grid view"
              >
                <Grid3x3 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setViewMode('list')}
                className={`rounded-none ${viewMode === 'list' ? 'bg-amber-bg text-amber-text' : ''}`}
                aria-label="List view"
              >
                <List className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setViewMode('graph')}
                className={`rounded-l-none ${viewMode === 'graph' ? 'bg-amber-bg text-amber-text' : ''}`}
                aria-label="Graph view"
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
            const health = getMockHealth(project.slug)
            return (
              <Card
                key={`card-${project.id}`}
                className={`cursor-pointer p-5 transition-shadow hover:shadow-md ${''}`}
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
                  <div
                    className={`flex h-12 w-12 items-center justify-center rounded-full ring-4 ${getHealthRingColor(
                      health,
                    )} ${getHealthColor(health)} ml-3 flex-shrink-0`}
                  >
                    <span className="text-sm font-semibold">{health}</span>
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
                        name={env.name}
                        slug={env.slug}
                        label_color={env.label_color}
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
            <table className="w-full">
              <thead className="border-b border-tertiary bg-secondary">
                <tr>
                  <th
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Project
                  </th>
                  <th
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Type
                  </th>
                  <th
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Team
                  </th>
                  <th
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Environments
                  </th>
                  <th
                    className={
                      'px-6 py-3 text-left text-sm font-medium text-secondary'
                    }
                  >
                    Health
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-tertiary">
                {filteredProjects.map((project) => {
                  const health = getMockHealth(project.slug)
                  return (
                    <tr
                      key={`table-${project.id}`}
                      className="cursor-pointer transition-colors hover:bg-secondary"
                      onClick={() => handleProjectSelect(project.id)}
                    >
                      <td className="px-6 py-4 font-medium text-primary">
                        {project.name}
                      </td>
                      <td className="px-6 py-4 text-secondary">
                        {(project.project_types || [])
                          .map((pt) => pt.name)
                          .join(', ')}
                      </td>
                      <td className="px-6 py-4 text-secondary">
                        {project.team.name}
                      </td>
                      <td className="px-6 py-4">
                        {project.environments &&
                          project.environments.length > 0 && (
                            <div className="flex flex-wrap items-center gap-2">
                              {sortEnvironments(project.environments || []).map(
                                (env) => (
                                  <EnvironmentBadge
                                    key={env.slug}
                                    name={env.name}
                                    slug={env.slug}
                                    label_color={env.label_color}
                                  />
                                ),
                              )}
                            </div>
                          )}
                      </td>
                      <td className="px-6 py-4">
                        <div
                          className={`inline-flex h-10 w-10 items-center justify-center rounded-full ${getHealthColor(health)}`}
                        >
                          <span className="text-sm font-semibold">
                            {health}
                          </span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
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
