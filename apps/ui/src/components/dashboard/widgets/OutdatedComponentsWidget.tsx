import { Package, AlertTriangle, TrendingUp, ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'

interface OutdatedComponentsWidgetProps {
  isDarkMode: boolean
  onProjectSelect?: (projectId: string) => void
}

export function OutdatedComponentsWidget({ isDarkMode, onProjectSelect }: OutdatedComponentsWidgetProps) {
  const outdatedComponents = [
    {
      projectId: 'proj-123',
      project: 'frontend-applications/navigation',
      component: 'react',
      currentVersion: '17.0.2',
      latestVersion: '18.2.0',
      severity: 'high' as const,
      behindBy: 15,
      releaseDate: '2 months ago'
    },
    {
      projectId: 'proj-456',
      project: 'backend/api-gateway',
      component: 'express',
      currentVersion: '4.17.1',
      latestVersion: '4.18.2',
      severity: 'medium' as const,
      behindBy: 8,
      releaseDate: '3 weeks ago'
    },
    {
      projectId: 'proj-789',
      project: 'platform/deployment-service',
      component: 'node',
      currentVersion: '16.14.0',
      latestVersion: '20.10.0',
      severity: 'high' as const,
      behindBy: 4,
      releaseDate: '1 week ago'
    },
    {
      projectId: 'proj-234',
      project: 'security/auth-service',
      component: 'jsonwebtoken',
      currentVersion: '8.5.1',
      latestVersion: '9.0.2',
      severity: 'critical' as const,
      behindBy: 12,
      releaseDate: '1 month ago'
    },
    {
      projectId: 'proj-567',
      project: 'data/analytics-processor',
      component: 'pandas',
      currentVersion: '1.3.5',
      latestVersion: '2.1.4',
      severity: 'medium' as const,
      behindBy: 20,
      releaseDate: '2 weeks ago'
    }
  ]

  const severityConfig = {
    critical: { label: 'Critical', bgColor: isDarkMode ? 'bg-red-900/30' : 'bg-red-100', textColor: isDarkMode ? 'text-red-400' : 'text-red-700' },
    high: { label: 'High', bgColor: isDarkMode ? 'bg-orange-900/30' : 'bg-orange-100', textColor: isDarkMode ? 'text-orange-400' : 'text-orange-700' },
    medium: { label: 'Medium', bgColor: isDarkMode ? 'bg-yellow-900/30' : 'bg-yellow-100', textColor: isDarkMode ? 'text-yellow-400' : 'text-yellow-700' },
    low: { label: 'Low', bgColor: isDarkMode ? 'bg-blue-900/30' : 'bg-blue-100', textColor: isDarkMode ? 'text-blue-400' : 'text-blue-700' }
  }

  return (
    <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-lg ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Outdated Components
        </h3>
        <span className={`flex items-center gap-1 text-sm ${isDarkMode ? 'text-orange-400' : 'text-orange-600'}`}>
          <AlertTriangle className="w-4 h-4" />
          {outdatedComponents.length} need updates
        </span>
      </div>

      <div className="space-y-3">
        {outdatedComponents.map((item) => {
          const config = severityConfig[item.severity]

          return (
            <div
              key={item.projectId}
              className={`p-4 rounded-lg border transition-colors ${
                isDarkMode
                  ? 'bg-gray-750 border-gray-600 hover:border-gray-500'
                  : 'bg-white border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <Package className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <code className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                        {item.component}
                      </code>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs ${
                        config.bgColor
                      } ${config.textColor}`}>
                        {config.label}
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={() => onProjectSelect?.(item.projectId)}
                      className={`text-sm mb-2 hover:underline ${
                        isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'
                      }`}
                    >
                      {item.project}
                    </button>

                    <div className={`flex items-center gap-3 text-xs ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                      <span className="font-mono">
                        {item.currentVersion} → {item.latestVersion}
                      </span>
                      <span className={isDarkMode ? 'text-gray-600' : 'text-gray-400'}>•</span>
                      <span>{item.behindBy} version{item.behindBy !== 1 ? 's' : ''} behind</span>
                      <span className={isDarkMode ? 'text-gray-600' : 'text-gray-400'}>•</span>
                      <span>{item.releaseDate}</span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => onProjectSelect?.(item.projectId)}
                  className={`p-2 rounded transition-colors flex-shrink-0 ${
                    isDarkMode
                      ? 'hover:bg-gray-700 text-gray-400 hover:text-white'
                      : 'hover:bg-gray-100 text-gray-600 hover:text-gray-900'
                  }`}
                  aria-label={`View update details for ${item.component}`}
                >
                  <TrendingUp className="w-4 h-4" />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <div className={`mt-4 pt-4 border-t ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
        <button
          type="button"
          onClick={() => onProjectSelect?.('outdated-components')}
          className={`text-sm flex items-center gap-1 ${
            isDarkMode ? 'text-blue-400 hover:text-blue-300' : 'text-[#2A4DD0] hover:text-blue-700'
          }`}
        >
          View all outdated components
          <ExternalLink className="w-3 h-3" />
        </button>
      </div>
    </Card>
  )
}
