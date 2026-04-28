import { CheckCircle, ChevronRight, Clock, Rocket, XCircle } from 'lucide-react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

interface RecentDeploymentsWidgetProps {
  onProjectSelect?: (projectId: string) => void
}

export function RecentDeploymentsWidget({
  onProjectSelect,
}: RecentDeploymentsWidgetProps) {
  const deployments = [
    {
      deployedAt: '12 minutes ago',
      deployedBy: 'Scott Miller',
      environment: 'Production' as const,
      id: 1,
      project: 'frontend-applications/navigation',
      projectId: 'proj-123',
      status: 'success' as const,
      version: '3.68.0',
    },
    {
      deployedAt: '23 minutes ago',
      deployedBy: 'Dave Shawley',
      environment: 'Staging' as const,
      id: 2,
      project: 'backend/api-gateway',
      projectId: 'proj-456',
      status: 'in-progress' as const,
      version: '2.45.1',
    },
    {
      deployedAt: '1 hour ago',
      deployedBy: 'Gavin Roy',
      environment: 'Production' as const,
      id: 3,
      project: 'platform/deployment-service',
      projectId: 'proj-789',
      status: 'failed' as const,
      version: '1.12.3',
    },
    {
      deployedAt: '2 hours ago',
      deployedBy: 'Jim Fitzpatrick',
      environment: 'Production' as const,
      id: 4,
      project: 'security/auth-service',
      projectId: 'proj-234',
      status: 'success' as const,
      version: '4.2.0',
    },
    {
      deployedAt: '3 hours ago',
      deployedBy: 'Scott Miller',
      environment: 'Testing' as const,
      id: 5,
      project: 'data/analytics-processor',
      projectId: 'proj-567',
      status: 'success' as const,
      version: '5.8.2',
    },
  ]

  const statusConfig: Record<
    'failed' | 'in-progress' | 'success',
    { icon: typeof CheckCircle; label: string; variant: BadgeProps['variant'] }
  > = {
    failed: { icon: XCircle, label: 'Failed', variant: 'danger' },
    'in-progress': { icon: Clock, label: 'In Progress', variant: 'info' },
    success: { icon: CheckCircle, label: 'Success', variant: 'success' },
  }

  const envConfig: Record<
    'Production' | 'Staging' | 'Testing',
    { variant: BadgeProps['variant'] }
  > = {
    Production: { variant: 'accent' },
    Staging: { variant: 'warning' },
    Testing: { variant: 'info' },
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg text-primary">Recent Deployments</h3>
      </div>

      <div className="space-y-2">
        {deployments.map((deployment) => {
          const status = statusConfig[deployment.status]
          const env = envConfig[deployment.environment]
          const StatusIcon = status.icon

          return (
            <button
              className="w-full rounded-lg border border-input bg-background p-3 text-left transition-colors hover:border-secondary"
              key={deployment.id}
              onClick={() => onProjectSelect?.(deployment.projectId)}
              type="button"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Rocket className="mt-0.5 h-5 w-5 flex-shrink-0 text-tertiary" />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 truncate font-medium text-primary">
                      {deployment.project}
                    </div>
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <code className="rounded bg-secondary px-2 py-0.5 text-xs text-primary">
                        {deployment.version}
                      </code>
                      <Badge className="rounded-full" variant={env.variant}>
                        {deployment.environment}
                      </Badge>
                      <Badge
                        className="gap-1 rounded-full"
                        variant={status.variant}
                      >
                        <StatusIcon className="h-3 w-3" />
                        {status.label}
                      </Badge>
                    </div>
                    <div className="text-xs text-gray-500">
                      {deployment.deployedBy} • {deployment.deployedAt}
                    </div>
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 flex-shrink-0 text-tertiary" />
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}
