import { Package, AlertTriangle, TrendingUp, ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'

interface OutdatedComponentsWidgetProps {
  isDarkMode: boolean
  onProjectSelect?: (projectId: string) => void
}

export function OutdatedComponentsWidget({
  isDarkMode,
  onProjectSelect,
}: OutdatedComponentsWidgetProps) {
  const outdatedComponents = [
    {
      projectId: 'proj-123',
      project: 'frontend-applications/navigation',
      component: 'react',
      currentVersion: '17.0.2',
      latestVersion: '18.2.0',
      severity: 'high' as const,
      behindBy: 15,
      releaseDate: '2 months ago',
    },
    {
      projectId: 'proj-456',
      project: 'backend/api-gateway',
      component: 'express',
      currentVersion: '4.17.1',
      latestVersion: '4.18.2',
      severity: 'medium' as const,
      behindBy: 8,
      releaseDate: '3 weeks ago',
    },
    {
      projectId: 'proj-789',
      project: 'platform/deployment-service',
      component: 'node',
      currentVersion: '16.14.0',
      latestVersion: '20.10.0',
      severity: 'high' as const,
      behindBy: 4,
      releaseDate: '1 week ago',
    },
    {
      projectId: 'proj-234',
      project: 'security/auth-service',
      component: 'jsonwebtoken',
      currentVersion: '8.5.1',
      latestVersion: '9.0.2',
      severity: 'critical' as const,
      behindBy: 12,
      releaseDate: '1 month ago',
    },
    {
      projectId: 'proj-567',
      project: 'data/analytics-processor',
      component: 'pandas',
      currentVersion: '1.3.5',
      latestVersion: '2.1.4',
      severity: 'medium' as const,
      behindBy: 20,
      releaseDate: '2 weeks ago',
    },
  ]

  const severityConfig = {
    critical: {
      label: 'Critical',
      bgColor: isDarkMode ? 'bg-red-900/30' : 'bg-red-100',
      textColor: isDarkMode ? 'text-red-400' : 'text-red-700',
    },
    high: {
      label: 'High',
      bgColor: isDarkMode ? 'bg-orange-900/30' : 'bg-orange-100',
      textColor: isDarkMode ? 'text-orange-400' : 'text-orange-700',
    },
    medium: {
      label: 'Medium',
      bgColor: isDarkMode ? 'bg-yellow-900/30' : 'bg-yellow-100',
      textColor: isDarkMode ? 'text-yellow-400' : 'text-yellow-700',
    },
    low: {
      label: 'Low',
      bgColor: isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100',
      textColor: isDarkMode ? 'text-blue-400' : 'text-blue-700',
    },
  }

  return (
    <Card className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}>
      <div className="mb-4 flex items-center justify-between">
        <h3
          className={`text-lg ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Outdated Components
        </h3>
        <span
          className={`flex items-center gap-1 text-sm ${isDarkMode ? 'text-orange-400' : 'text-orange-600'}`}
        >
          <AlertTriangle className="h-4 w-4" />
          {outdatedComponents.length} need updates
        </span>
      </div>

      <div className="space-y-3">
        {outdatedComponents.map((item) => {
          const config = severityConfig[item.severity]

          return (
            <div
              key={item.projectId}
              className={`rounded-lg border p-4 transition-colors ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700 hover:border-gray-500'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Package
                    className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <code
                        className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                      >
                        {item.component}
                      </code>
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                          config.bgColor
                        } ${config.textColor}`}
                      >
                        {config.label}
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={() => onProjectSelect?.(item.projectId)}
                      className={`mb-2 text-sm hover:underline ${
                        isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'
                      }`}
                    >
                      {item.project}
                    </button>

                    <div
                      className={`flex items-center gap-3 text-xs ${
                        isDarkMode ? 'text-gray-400' : 'text-gray-600'
                      }`}
                    >
                      <span className="font-mono">
                        {item.currentVersion} → {item.latestVersion}
                      </span>
                      <span
                        className={
                          isDarkMode ? 'text-gray-600' : 'text-gray-400'
                        }
                      >
                        •
                      </span>
                      <span>
                        {item.behindBy} version{item.behindBy !== 1 ? 's' : ''}{' '}
                        behind
                      </span>
                      <span
                        className={
                          isDarkMode ? 'text-gray-600' : 'text-gray-400'
                        }
                      >
                        •
                      </span>
                      <span>{item.releaseDate}</span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => onProjectSelect?.(item.projectId)}
                  className={`flex-shrink-0 rounded p-2 transition-colors ${
                    isDarkMode
                      ? 'text-gray-400 hover:bg-gray-700 hover:text-white'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                  aria-label={`View update details for ${item.component}`}
                >
                  <TrendingUp className="h-4 w-4" />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <div
        className={`mt-4 border-t pt-4 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
      >
        <button
          type="button"
          onClick={() => onProjectSelect?.('outdated-components')}
          className={`flex items-center gap-1 text-sm ${
            isDarkMode
              ? 'text-blue-400 hover:text-blue-300'
              : 'text-[#2A4DD0] hover:text-blue-700'
          }`}
        >
          View all outdated components
          <ExternalLink className="h-3 w-3" />
        </button>
      </div>
    </Card>
  )
}
