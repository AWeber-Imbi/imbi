import { Search, Filter, Plus, Grid3x3, List } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Card } from './ui/card'
import { Badge } from './ui/badge'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getProjects } from '@/api/endpoints'

interface ProjectsViewProps {
  onProjectSelect: (projectId: string) => void
  filter?: { namespace?: string } | null
  isDarkMode: boolean
}

export function ProjectsView({ onProjectSelect, filter, isDarkMode }: ProjectsViewProps) {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [searchQuery, setSearchQuery] = useState('')

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => getProjects(),
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

  // Mock health score - in reality this would come from the API
  const getMockHealth = () => Math.floor(70 + Math.random() * 30)

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-center h-64">
          <div className="text-lg">Loading projects...</div>
        </div>
      </div>
    )
  }

  // Filter projects based on search and filters
  let filteredProjects = projects || []

  if (searchQuery) {
    const query = searchQuery.toLowerCase()
    filteredProjects = filteredProjects.filter(
      p => p.name.toLowerCase().includes(query) ||
           p.description?.toLowerCase().includes(query) ||
           p.namespace.toLowerCase().includes(query)
    )
  }

  if (filter?.namespace) {
    filteredProjects = filteredProjects.filter(p => p.namespace === filter.namespace)
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
            Projects
          </h1>
          <Button size="sm" className="bg-green-600 hover:bg-green-700">
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

            <Button
              variant="outline"
              size="sm"
              className={filter ? 'border-blue-500 text-blue-700' : ''}
            >
              <Filter className="w-4 h-4 mr-2" />
              Filter
              {filter && (
                <Badge variant="secondary" className="ml-2 bg-blue-100 text-blue-700">
                  1
                </Badge>
              )}
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

      {/* Active Filter Display */}
      {filter && (
        <Card className="p-4 mb-6 bg-blue-50 border-blue-200">
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <Filter className="w-4 h-4 text-blue-700" />
                <span className="text-blue-900">Active Filter</span>
              </div>
              <div className="text-sm text-blue-800">
                Namespace: <span className="font-medium">{filter.namespace}</span>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Projects Grid/List */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredProjects.map((project) => {
            const health = getMockHealth()
            return (
              <Card
                key={project.id}
                className={`p-5 hover:shadow-md transition-shadow cursor-pointer ${
                  isDarkMode ? 'bg-gray-800 border-gray-700' : ''
                }`}
                onClick={() => onProjectSelect(project.id.toString())}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className={`mb-1 truncate font-medium ${
                      isDarkMode ? 'text-white' : 'text-slate-900'
                    }`}>
                      {project.name}
                    </h3>
                    <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
                      {project.project_type}
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
                    {project.namespace}
                  </p>
                </div>

                {project.environments && project.environments.length > 0 && (
                  <div className="flex items-center gap-2 flex-wrap">
                    {project.environments.map((env, index) => (
                      <span
                        key={index}
                        className={`px-2 py-1 rounded text-xs ${getEnvironmentBadgeColor(env)}`}
                      >
                        {env}
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
                  <th className={`text-left px-6 py-3 text-sm font-medium ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-700'
                  }`}>
                    Project
                  </th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-700'
                  }`}>
                    Type
                  </th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-700'
                  }`}>
                    Namespace
                  </th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-700'
                  }`}>
                    Environments
                  </th>
                  <th className={`text-left px-6 py-3 text-sm font-medium ${
                    isDarkMode ? 'text-gray-300' : 'text-slate-700'
                  }`}>
                    Health
                  </th>
                </tr>
              </thead>
              <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-slate-200'}`}>
                {filteredProjects.map((project) => {
                  const health = getMockHealth()
                  return (
                    <tr
                      key={project.id}
                      className={`transition-colors cursor-pointer ${
                        isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-slate-50'
                      }`}
                      onClick={() => onProjectSelect(project.id.toString())}
                    >
                      <td className={`px-6 py-4 font-medium ${
                        isDarkMode ? 'text-white' : 'text-slate-900'
                      }`}>
                        {project.name}
                      </td>
                      <td className={`px-6 py-4 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                        {project.project_type}
                      </td>
                      <td className={`px-6 py-4 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                        {project.namespace}
                      </td>
                      <td className="px-6 py-4">
                        {project.environments && project.environments.length > 0 && (
                          <div className="flex items-center gap-2 flex-wrap">
                            {project.environments.map((env, index) => (
                              <span
                                key={index}
                                className={`px-2 py-1 rounded text-xs ${getEnvironmentBadgeColor(env)}`}
                              >
                                {env}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <div className={`inline-flex items-center justify-center w-10 h-10 rounded-full ${
                          getHealthColor(health)
                        }`}>
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
    </div>
  )
}
