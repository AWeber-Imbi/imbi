import { Rocket, CheckCircle, XCircle, Clock, ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/card'

interface RecentDeploymentsWidgetProps {
  isDarkMode: boolean
  onProjectSelect?: (projectId: string) => void
}

export function RecentDeploymentsWidget({
  isDarkMode,
  onProjectSelect,
}: RecentDeploymentsWidgetProps) {
  const deployments = [
    {
      id: 1,
      projectId: 'proj-123',
      project: 'frontend-applications/navigation',
      version: '3.68.0',
      environment: 'Production' as const,
      status: 'success' as const,
      deployedBy: 'Scott Miller',
      deployedAt: '12 minutes ago',
    },
    {
      id: 2,
      projectId: 'proj-456',
      project: 'backend/api-gateway',
      version: '2.45.1',
      environment: 'Staging' as const,
      status: 'in-progress' as const,
      deployedBy: 'Dave Shawley',
      deployedAt: '23 minutes ago',
    },
    {
      id: 3,
      projectId: 'proj-789',
      project: 'platform/deployment-service',
      version: '1.12.3',
      environment: 'Production' as const,
      status: 'failed' as const,
      deployedBy: 'Gavin Roy',
      deployedAt: '1 hour ago',
    },
    {
      id: 4,
      projectId: 'proj-234',
      project: 'security/auth-service',
      version: '4.2.0',
      environment: 'Production' as const,
      status: 'success' as const,
      deployedBy: 'Jim Fitzpatrick',
      deployedAt: '2 hours ago',
    },
    {
      id: 5,
      projectId: 'proj-567',
      project: 'data/analytics-processor',
      version: '5.8.2',
      environment: 'Testing' as const,
      status: 'success' as const,
      deployedBy: 'Scott Miller',
      deployedAt: '3 hours ago',
    },
  ]

  const statusConfig = {
    success: {
      label: 'Success',
      icon: CheckCircle,
      color: isDarkMode ? 'text-green-400' : 'text-green-600',
      bgColor: isDarkMode ? 'bg-green-900/30' : 'bg-green-100',
    },
    failed: {
      label: 'Failed',
      icon: XCircle,
      color: isDarkMode ? 'text-red-400' : 'text-red-600',
      bgColor: isDarkMode ? 'bg-red-900/30' : 'bg-red-100',
    },
    'in-progress': {
      label: 'In Progress',
      icon: Clock,
      color: isDarkMode ? 'text-blue-400' : 'text-blue-600',
      bgColor: isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100',
    },
  }

  const envConfig = {
    Production: {
      color: isDarkMode ? 'text-purple-400' : 'text-purple-600',
      bgColor: isDarkMode ? 'bg-purple-900/30' : 'bg-purple-100',
    },
    Staging: {
      color: isDarkMode ? 'text-yellow-400' : 'text-yellow-600',
      bgColor: isDarkMode ? 'bg-yellow-900/30' : 'bg-yellow-100',
    },
    Testing: {
      color: isDarkMode ? 'text-blue-400' : 'text-blue-600',
      bgColor: isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100',
    },
  }

  return (
    <Card className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}>
      <div className="mb-4 flex items-center justify-between">
        <h3
          className={`text-lg ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Recent Deployments
        </h3>
      </div>

      <div className="space-y-2">
        {deployments.map((deployment) => {
          const status = statusConfig[deployment.status]
          const env = envConfig[deployment.environment]
          const StatusIcon = status.icon

          return (
            <button
              type="button"
              key={deployment.id}
              onClick={() => onProjectSelect?.(deployment.projectId)}
              className={`w-full rounded-lg border p-3 text-left transition-colors ${
                isDarkMode
                  ? 'bg-gray-750 border-gray-600 hover:border-gray-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Rocket
                    className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div
                      className={`mb-1 truncate font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                    >
                      {deployment.project}
                    </div>
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <code
                        className={`rounded px-2 py-0.5 text-xs ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {deployment.version}
                      </code>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                          env.bgColor
                        } ${env.color}`}
                      >
                        {deployment.environment}
                      </span>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                          status.bgColor
                        } ${status.color}`}
                      >
                        <StatusIcon className="h-3 w-3" />
                        {status.label}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500">
                      {deployment.deployedBy} • {deployment.deployedAt}
                    </div>
                  </div>
                </div>
                <ChevronRight
                  className={`h-4 w-4 flex-shrink-0 ${
                    isDarkMode ? 'text-gray-600' : 'text-gray-400'
                  }`}
                />
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}
