import { TrendingUp, TrendingDown, CheckCircle, XCircle, AlertTriangle, ChevronRight } from 'lucide-react'
import { Card } from './ui/card'
import { RecentActivity } from './RecentActivity'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useInfiniteActivityFeed } from '@/hooks/useInfiniteActivityFeed'
import { getProjects } from '@/api/endpoints'
import type { Project } from '@/types'

interface DashboardProps {
  onViewChange?: (view: any) => void
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
  isDarkMode: boolean
}

export function Dashboard({ onViewChange, onUserSelect, onProjectSelect, isDarkMode }: DashboardProps) {
  const [viewMode, setViewMode] = useState<'namespaces' | 'project-types' | 'recent-activity'>('namespaces')

  // Fetch real data
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => getProjects(),
  })

  const {
    data: activityData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: activityLoading,
  } = useInfiniteActivityFeed()

  const activityFeed = activityData?.activities || []

  const handleNamespaceClick = (namespaceName: string) => {
    onViewChange?.({ view: 'projects', filter: { namespace: namespaceName } })
  }

  const handleDeploymentClick = (e: React.MouseEvent, namespaceName: string) => {
    e.stopPropagation()
    onViewChange?.({ view: 'deployments', filter: { namespace: namespaceName } })
  }

  // Group real projects by namespace
  const projectsByNamespace = projects?.reduce((acc, project) => {
    if (!acc[project.namespace]) {
      acc[project.namespace] = []
    }
    acc[project.namespace].push(project)
    return acc
  }, {} as Record<string, Project[]>) || {}

  // Group by project type
  const projectsByType = projects?.reduce((acc, project) => {
    if (!acc[project.project_type]) {
      acc[project.project_type] = []
    }
    acc[project.project_type].push(project)
    return acc
  }, {} as Record<string, Project[]>) || {}

  const stats = [
    { label: 'Total Projects', value: (projects?.length || 0).toString(), change: '+12', trend: 'up' },
    { label: 'Active Deployments', value: '445', change: '+5', trend: 'up' },
    { label: 'Avg Health Score', value: '87%', change: '+3%', trend: 'up' },
    { label: 'Deployments Today', value: '34', change: '+8', trend: 'up' }
  ]

  // Mock function for environment health (TODO: get real deployment data)
  const getEnvironmentHealth = (projects: Project[]) => {
    const envHealth = {
      testing: { success: 0, warning: 0, error: 0, total: 0 },
      staging: { success: 0, warning: 0, error: 0, total: 0 },
      production: { success: 0, warning: 0, error: 0, total: 0 }
    }

    // Mock data - distribute projects across statuses
    const count = projects.length
    envHealth.testing.success = Math.floor(count * 0.7)
    envHealth.testing.warning = Math.floor(count * 0.2)
    envHealth.testing.error = count - envHealth.testing.success - envHealth.testing.warning

    envHealth.staging.success = Math.floor(count * 0.75)
    envHealth.staging.warning = Math.floor(count * 0.15)
    envHealth.staging.error = count - envHealth.staging.success - envHealth.staging.warning

    envHealth.production.success = Math.floor(count * 0.8)
    envHealth.production.warning = Math.floor(count * 0.1)
    envHealth.production.error = count - envHealth.production.success - envHealth.production.warning

    return envHealth
  }

  const getHealthScore = (_projects: Project[]) => {
    // Mock health score calculation
    return Math.floor(85 + Math.random() * 10)
  }

  const getHealthColor = (health: number) => {
    if (health >= 90) return 'text-green-600'
    if (health >= 80) return 'text-emerald-600'
    if (health >= 70) return 'text-amber-600'
    return 'text-red-600'
  }

  if (projectsLoading || activityLoading) {
    return (
      <div className="max-w-[1600px] mx-auto px-6 py-8">
        <div className="flex items-center justify-center h-64">
          <div className="text-lg">Loading dashboard...</div>
        </div>
      </div>
    )
  }

  const displayItems = viewMode === 'namespaces'
    ? Object.entries(projectsByNamespace).map(([name, projects]) => ({ name, projects }))
    : Object.entries(projectsByType).map(([name, projects]) => ({ name, projects }))

  return (
    <div className="max-w-[1600px] mx-auto px-6 py-8">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {stats.map((stat, index) => (
          <Card key={index} className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
            <div className="flex items-start justify-between">
              <div>
                <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>{stat.label}</p>
                <p className={`text-3xl mb-2 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>{stat.value}</p>
                <div className="flex items-center gap-1">
                  {stat.trend === 'up' ? (
                    <TrendingUp className="w-3 h-3 text-green-600" />
                  ) : (
                    <TrendingDown className="w-3 h-3 text-green-600" />
                  )}
                  <span className="text-green-600 text-sm">{stat.change}</span>
                  <span className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>this week</span>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Integrated Namespace + Deployment View */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Namespace/Project Type Cards - 2/3 width */}
        <div className="lg:col-span-2">
          {/* Tab Navigation - Underline Style */}
          <div className={`border-b mb-4 ${isDarkMode ? 'border-gray-700' : 'border-slate-200'}`}>
            <div className="flex gap-6">
              <button
                onClick={() => setViewMode('namespaces')}
                className={`pb-3 border-b-2 transition-colors whitespace-nowrap ${
                  viewMode === 'namespaces'
                    ? 'border-blue-600 text-blue-600'
                    : isDarkMode
                      ? 'border-transparent text-gray-400 hover:text-white hover:border-gray-600'
                      : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
                }`}
              >
                Namespaces
              </button>
              <button
                onClick={() => setViewMode('project-types')}
                className={`pb-3 border-b-2 transition-colors whitespace-nowrap ${
                  viewMode === 'project-types'
                    ? 'border-blue-600 text-blue-600'
                    : isDarkMode
                      ? 'border-transparent text-gray-400 hover:text-white hover:border-gray-600'
                      : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
                }`}
              >
                Project Types
              </button>
            </div>
          </div>

          {/* Render cards based on view mode */}
          {viewMode !== 'recent-activity' && (
            <div className="space-y-3">
              {displayItems
                .sort((a, b) => b.projects.length - a.projects.length)
                .map((item) => {
                  const envHealth = getEnvironmentHealth(item.projects)
                  const health = getHealthScore(item.projects)

                  return (
                    <Card
                      key={item.name}
                      className={`overflow-hidden hover:shadow-md transition-shadow cursor-pointer ${
                        isDarkMode ? 'bg-gray-800 border-gray-700' : ''
                      }`}
                      onClick={() => handleNamespaceClick(item.name)}
                    >
                      <div className="px-6 py-4">
                        <div className="flex items-center justify-between gap-6">
                          {/* Left: Namespace Info */}
                          <div className="flex-shrink-0" style={{ width: '280px' }}>
                            <h3 className={isDarkMode ? 'text-white mb-1' : 'text-slate-900 mb-1'}>{item.name}</h3>
                            <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
                              {item.projects.length} projects
                            </p>
                          </div>

                          {/* Center: Environment Health */}
                          <div
                            className="flex-1 flex items-center gap-12 -my-4 py-4 rounded transition-colors"
                            onClick={(e) => handleDeploymentClick(e, item.name)}
                          >
                            {/* Testing */}
                            <div className="text-center" style={{ width: '120px' }}>
                              <div className={`text-xs mb-2 ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>Testing</div>
                              <div className="flex items-center justify-center gap-3">
                                {envHealth.testing.success > 0 && (
                                  <div className="flex items-center gap-1">
                                    <CheckCircle className="w-4 h-4 text-green-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.testing.success}
                                    </span>
                                  </div>
                                )}
                                {envHealth.testing.warning > 0 && (
                                  <div className="flex items-center gap-1">
                                    <AlertTriangle className="w-4 h-4 text-amber-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.testing.warning}
                                    </span>
                                  </div>
                                )}
                                {envHealth.testing.error > 0 && (
                                  <div className="flex items-center gap-1">
                                    <XCircle className="w-4 h-4 text-red-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.testing.error}
                                    </span>
                                  </div>
                                )}
                              </div>
                            </div>

                            {/* Staging */}
                            <div className="text-center" style={{ width: '120px' }}>
                              <div className={`text-xs mb-2 ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>Staging</div>
                              <div className="flex items-center justify-center gap-3">
                                {envHealth.staging.success > 0 && (
                                  <div className="flex items-center gap-1">
                                    <CheckCircle className="w-4 h-4 text-green-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.staging.success}
                                    </span>
                                  </div>
                                )}
                                {envHealth.staging.warning > 0 && (
                                  <div className="flex items-center gap-1">
                                    <AlertTriangle className="w-4 h-4 text-amber-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.staging.warning}
                                    </span>
                                  </div>
                                )}
                                {envHealth.staging.error > 0 && (
                                  <div className="flex items-center gap-1">
                                    <XCircle className="w-4 h-4 text-red-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.staging.error}
                                    </span>
                                  </div>
                                )}
                              </div>
                            </div>

                            {/* Production */}
                            <div className="text-center" style={{ width: '120px' }}>
                              <div className={`text-xs mb-2 ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>Production</div>
                              <div className="flex items-center justify-center gap-3">
                                {envHealth.production.success > 0 && (
                                  <div className="flex items-center gap-1">
                                    <CheckCircle className="w-4 h-4 text-green-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.production.success}
                                    </span>
                                  </div>
                                )}
                                {envHealth.production.warning > 0 && (
                                  <div className="flex items-center gap-1">
                                    <AlertTriangle className="w-4 h-4 text-amber-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.production.warning}
                                    </span>
                                  </div>
                                )}
                                {envHealth.production.error > 0 && (
                                  <div className="flex items-center gap-1">
                                    <XCircle className="w-4 h-4 text-red-600" />
                                    <span className={`text-sm ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                                      {envHealth.production.error}
                                    </span>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Right: Health Score */}
                          <div className="flex-shrink-0 flex items-center gap-2">
                            <TrendingUp className="w-4 h-4 text-green-600" />
                            <span className={`text-2xl ${getHealthColor(health)}`}>
                              {health}
                            </span>
                            <ChevronRight className={`w-5 h-5 ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`} />
                          </div>
                        </div>
                      </div>
                    </Card>
                  )
                })}
            </div>
          )}
        </div>

        {/* Recent Activity - 1/3 width */}
        <div className="lg:col-span-1">
          {/* Tab Navigation - Underline Style */}
          <div className={`border-b mb-4 ${isDarkMode ? 'border-gray-700' : 'border-slate-200'}`}>
            <div className="flex gap-6">
              <button
                onClick={() => setViewMode('recent-activity')}
                className={`pb-3 border-b-2 transition-colors whitespace-nowrap ${
                  viewMode === 'recent-activity'
                    ? 'border-blue-600 text-blue-600'
                    : isDarkMode
                      ? 'border-transparent text-gray-400 hover:text-white hover:border-gray-600'
                      : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
                }`}
              >
                Recent Activity
              </button>
            </div>
          </div>

          <RecentActivity
            activities={activityFeed}
            onUserSelect={onUserSelect}
            onProjectSelect={onProjectSelect}
            isDarkMode={isDarkMode}
            hideHeading={true}
            onLoadMore={hasNextPage ? () => fetchNextPage() : undefined}
            isLoadingMore={isFetchingNextPage}
          />
        </div>
      </div>
    </div>
  )
}
