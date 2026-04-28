import { AlertTriangle, ExternalLink, Package, TrendingUp } from 'lucide-react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

interface OutdatedComponentsWidgetProps {
  onProjectSelect?: (projectId: string) => void
}

export function OutdatedComponentsWidget({
  onProjectSelect,
}: OutdatedComponentsWidgetProps) {
  const outdatedComponents = [
    {
      behindBy: 15,
      component: 'react',
      currentVersion: '17.0.2',
      latestVersion: '18.2.0',
      project: 'frontend-applications/navigation',
      projectId: 'proj-123',
      releaseDate: '2 months ago',
      severity: 'high' as const,
    },
    {
      behindBy: 8,
      component: 'express',
      currentVersion: '4.17.1',
      latestVersion: '4.18.2',
      project: 'backend/api-gateway',
      projectId: 'proj-456',
      releaseDate: '3 weeks ago',
      severity: 'medium' as const,
    },
    {
      behindBy: 4,
      component: 'node',
      currentVersion: '16.14.0',
      latestVersion: '20.10.0',
      project: 'platform/deployment-service',
      projectId: 'proj-789',
      releaseDate: '1 week ago',
      severity: 'high' as const,
    },
    {
      behindBy: 12,
      component: 'jsonwebtoken',
      currentVersion: '8.5.1',
      latestVersion: '9.0.2',
      project: 'security/auth-service',
      projectId: 'proj-234',
      releaseDate: '1 month ago',
      severity: 'critical' as const,
    },
    {
      behindBy: 20,
      component: 'pandas',
      currentVersion: '1.3.5',
      latestVersion: '2.1.4',
      project: 'data/analytics-processor',
      projectId: 'proj-567',
      releaseDate: '2 weeks ago',
      severity: 'medium' as const,
    },
  ]

  const severityConfig: Record<
    'critical' | 'high' | 'low' | 'medium',
    { label: string; variant: BadgeProps['variant'] }
  > = {
    critical: { label: 'Critical', variant: 'danger' },
    high: { label: 'High', variant: 'warning' },
    low: { label: 'Low', variant: 'info' },
    medium: { label: 'Medium', variant: 'warning' },
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
              className="rounded-lg border border-input bg-background p-4 transition-colors hover:border-secondary"
              key={item.projectId}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Package className="mt-0.5 h-5 w-5 flex-shrink-0 text-tertiary" />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <code className="text-sm font-medium text-primary">
                        {item.component}
                      </code>
                      <Badge className="rounded-full" variant={config.variant}>
                        {config.label}
                      </Badge>
                    </div>

                    <button
                      className="mb-2 text-sm text-info hover:underline"
                      onClick={() => onProjectSelect?.(item.projectId)}
                      type="button"
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
                  aria-label={`View update details for ${item.component}`}
                  className="flex-shrink-0 rounded p-2 text-secondary transition-colors hover:bg-secondary hover:text-primary"
                  onClick={() => onProjectSelect?.(item.projectId)}
                  type="button"
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
          className="hover:text-info/80 flex items-center gap-1 text-sm text-info"
          onClick={() => onProjectSelect?.('outdated-components')}
          type="button"
        >
          View all outdated components
          <ExternalLink className="h-3 w-3" />
        </button>
      </div>
    </Card>
  )
}
