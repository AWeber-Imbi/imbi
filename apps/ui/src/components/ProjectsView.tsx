import { Search, Filter, Plus, Grid3x3, List } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Card } from './ui/card'
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getProjects } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { NewProjectDialog } from './NewProjectDialog'

interface ProjectsViewProps {
  isDarkMode: boolean
}

export function ProjectsView({ isDarkMode }: ProjectsViewProps) {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [searchQuery, setSearchQuery] = useState('')
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects', orgSlug],
    queryFn: () => getProjects(orgSlug),
    enabled: !!orgSlug,
  })

  const getHealthColor = (health: number) => {
    if (health >= 90) return 'text-green-600 bg-green-100'
    if (health >= 80) return 'text-emerald-600 bg-emerald-100'
    if (health >= 70) return 'text-amber-600 bg-amber-100'
    return 'text-red-600 bg-red-100'
  }

  const getHealthRingColor = (health: number) => {
    if (health >= 90) return 'ring-green-200'
    if (health >= 80) return 'ring-emerald-200'
    if (health >= 70) return 'ring-amber-200'
    return 'ring-red-200'
  }

  const getEnvironmentBadgeColor = (env: string) => {
    const envLower = env.toLowerCase()
    if (envLower.includes('prod')) return 'bg-red-100 text-red-700'
    if (envLower.includes('stag')) return 'bg-amber-100 text-amber-700'
    return 'bg-blue-100 text-blue-700'
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

  const handleProjectSelect = (slug: string) => {
    navigate(`/projects/${slug}`)
  }

  const filteredProjects = useMemo(() => {
    const all = projects || []
    if (!searchQuery) return all
    const query = searchQuery.toLowerCase()
    return all.filter(p => {
      return p.name.toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.team.name.toLowerCase().includes(query) ||
        p.project_type.name.toLowerCase().includes(query)
    })
  }, [projects, searchQuery])

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-center h-64">
          <div className="text-lg">Loading projects...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
            Projects
          </h1>
          <Button
            size="sm"
            className="bg-green-600 hover:bg-green-700"
            onClick={() => setNewProjectDialogOpen(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            New Project
          </Button>
        </div>

        {/* Search and Filters */}
        <Card className={`p-4 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
                isDarkMode ? 'text-gray-400' : 'text-slate-400'
              }`} />
              <Input
                type="text"
                placeholder="Search projects..."
                className={`pl-9 ${
                  isDarkMode ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400' : ''
                }`}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <Button variant="outline" size="sm">
              <Filter className="w-4 h-4 mr-2" />
              Filter
            </Button>

            <div className={`flex items-center border rounded-lg ${
              isDarkMode ? 'border-gray-600' : 'border-slate-200'
            }`}>
              <Button
                variant={viewMode === 'grid' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('grid')}
                className="rounded-r-none"
              >
                <Grid3x3 className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'list' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('list')}
                className="rounded-l-none"
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </Card>
      </div>

      {/* Projects Grid/List */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredProjects.map((project, index) => {
            const health = getMockHealth(project.slug)
            return (
              <Card
                key={`${index}-${project.project_type.slug}/${project.slug}`}
                className={`p-5 hover:shadow-md transition-shadow cursor-pointer ${
                  isDarkMode ? 'bg-gray-800 border-gray-700' : ''
                }`}
                onClick={() => handleProjectSelect(project.slug)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className={`mb-1 truncate font-medium ${
                      isDarkMode ? 'text-white' : 'text-slate-900'
                    }`}>
                      {project.name}
                    </h3>
                    <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
                      {project.project_type.name}
                    </p>
                  </div>
                  <div className={`flex items-center justify-center w-12 h-12 rounded-full ring-4 ${
                    getHealthRingColor(health)
                  } ${getHealthColor(health)} flex-shrink-0 ml-3`}>
                    <span className="text-sm font-semibold">{health}</span>
                  </div>
                </div>

                {project.description && (
                  <p className={`text-sm mb-3 line-clamp-2 ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-600'
                  }`}>
                    {project.description}
                  </p>
                )}

                <div className="mb-3">
                  <p className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-slate-500'}`}>
                    {project.team.name}
                  </p>
                </div>

                {project.environments && project.environments.length > 0 && (
                  <div className="flex items-center gap-2 flex-wrap">
                    {project.environments.map((env, envIdx) => (
                      <span
                        key={envIdx}
                        className={`px-2 py-1 rounded text-xs ${getEnvironmentBadgeColor(env.name)}`}
                      >
                        {env.name}
                      </span>
                    ))}
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      ) : (
        <Card className={`overflow-hidden ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className={`border-b ${
                isDarkMode ? 'bg-gray-750 border-gray-700' : 'bg-slate-50 border-slate-200'
              }`}>
                <tr>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>Project</th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>Type</th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>Team</th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>Environments</th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}>Health</th>
                </tr>
              </thead>
              <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-slate-200'}`}>
                {filteredProjects.map((project, index) => {
                  const health = getMockHealth(project.slug)
                  return (
                    <tr
                      key={`${index}-${project.project_type.slug}/${project.slug}`}
                      className={`transition-colors cursor-pointer ${
                        isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-slate-50'
                      }`}
                      onClick={() => handleProjectSelect(project.slug)}
                    >
                      <td className={`px-6 py-4 font-medium ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                        {project.name}
                      </td>
                      <td className={`px-6 py-4 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                        {project.project_type.name}
                      </td>
                      <td className={`px-6 py-4 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                        {project.team.name}
                      </td>
                      <td className="px-6 py-4">
                        {project.environments && project.environments.length > 0 && (
                          <div className="flex items-center gap-2 flex-wrap">
                            {project.environments.map((env, envIdx) => (
                              <span
                                key={envIdx}
                                className={`px-2 py-1 rounded text-xs ${getEnvironmentBadgeColor(env.name)}`}
                              >
                                {env.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <div className={`inline-flex items-center justify-center w-10 h-10 rounded-full ${getHealthColor(health)}`}>
                          <span className="text-sm font-semibold">{health}</span>
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

      {filteredProjects.length === 0 && (
        <div className="text-center py-12">
          <p className={isDarkMode ? 'text-gray-400' : 'text-slate-500'}>
            No projects found matching your criteria
          </p>
        </div>
      )}

      <NewProjectDialog
        isOpen={newProjectDialogOpen}
        onClose={() => setNewProjectDialogOpen(false)}
        onProjectCreated={(slug) => navigate(`/projects/${slug}`)}
      />
    </div>
  )
}
