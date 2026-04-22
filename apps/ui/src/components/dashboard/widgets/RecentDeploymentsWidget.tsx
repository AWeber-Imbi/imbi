import { Rocket, CheckCircle, XCircle, Clock, ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge, type BadgeProps } from '@/components/ui/badge'

interface RecentDeploymentsWidgetProps {
  onProjectSelect?: (projectId: string) => void
}

export function RecentDeploymentsWidget({
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

  const statusConfig: Record<
    'success' | 'failed' | 'in-progress',
    { label: string; icon: typeof CheckCircle; variant: BadgeProps['variant'] }
  > = {
    success: { label: 'Success', icon: CheckCircle, variant: 'success' },
    failed: { label: 'Failed', icon: XCircle, variant: 'danger' },
    'in-progress': { label: 'In Progress', icon: Clock, variant: 'info' },
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
              type="button"
              key={deployment.id}
              onClick={() => onProjectSelect?.(deployment.projectId)}
              className={`w-full rounded-lg border border-input bg-background p-3 text-left transition-colors hover:border-secondary`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <Rocket
                    className={`mt-0.5 h-5 w-5 flex-shrink-0 text-tertiary`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 truncate font-medium text-primary">
                      {deployment.project}
                    </div>
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <code
                        className={`rounded bg-secondary px-2 py-0.5 text-xs text-primary`}
                      >
                        {deployment.version}
                      </code>
                      <Badge variant={env.variant} className="rounded-full">
                        {deployment.environment}
                      </Badge>
                      <Badge
                        variant={status.variant}
                        className="gap-1 rounded-full"
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
                <ChevronRight
                  className={`h-4 w-4 flex-shrink-0 text-tertiary`}
                />
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}
