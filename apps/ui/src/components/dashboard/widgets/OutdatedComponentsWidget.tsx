import { Package, AlertTriangle, TrendingUp, ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge, type BadgeProps } from '@/components/ui/badge'

interface OutdatedComponentsWidgetProps {
  onProjectSelect?: (projectId: string) => void
}

export function OutdatedComponentsWidget({
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

  const severityConfig: Record<
    'critical' | 'high' | 'medium' | 'low',
    { label: string; variant: BadgeProps['variant'] }
  > = {
    critical: { label: 'Critical', variant: 'danger' },
    high: { label: 'High', variant: 'warning' },
    medium: { label: 'Medium', variant: 'warning' },
    low: { label: 'Low', variant: 'info' },
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg text-primary">Outdated Components</h3>
        <span className="flex items-center gap-1 text-sm text-warning">
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
              className="rounded-lg border border-input bg-background p-4 transition-colors hover:border-secondary"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Package className="mt-0.5 h-5 w-5 flex-shrink-0 text-tertiary" />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <code className="text-sm font-medium text-primary">
                        {item.component}
                      </code>
                      <Badge variant={config.variant} className="rounded-full">
                        {config.label}
                      </Badge>
                    </div>

                    <button
                      type="button"
                      onClick={() => onProjectSelect?.(item.projectId)}
                      className="mb-2 text-sm text-info hover:underline"
                    >
                      {item.project}
                    </button>

                    <div className="flex items-center gap-3 text-xs text-secondary">
                      <span className="font-mono">
                        {item.currentVersion} → {item.latestVersion}
                      </span>
                      <span className="text-tertiary">•</span>
                      <span>
                        {item.behindBy} version{item.behindBy !== 1 ? 's' : ''}{' '}
                        behind
                      </span>
                      <span className="text-tertiary">•</span>
                      <span>{item.releaseDate}</span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => onProjectSelect?.(item.projectId)}
                  className="flex-shrink-0 rounded p-2 text-secondary transition-colors hover:bg-secondary hover:text-primary"
                  aria-label={`View update details for ${item.component}`}
                >
                  <TrendingUp className="h-4 w-4" />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-4 border-t border-tertiary pt-4">
        <button
          type="button"
          onClick={() => onProjectSelect?.('outdated-components')}
          className="hover:text-info/80 flex items-center gap-1 text-sm text-info"
        >
          View all outdated components
          <ExternalLink className="h-3 w-3" />
        </button>
      </div>
    </Card>
  )
}
