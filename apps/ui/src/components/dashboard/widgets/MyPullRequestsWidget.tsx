import { GitPullRequest, Clock, MessageSquare, CheckCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge, type BadgeProps } from '@/components/ui/badge'

interface MyPullRequestsWidgetProps {
  onUserSelect?: (userName: string) => void
}

export function MyPullRequestsWidget({
  onUserSelect,
}: MyPullRequestsWidgetProps) {
  const pullRequests = [
    {
      id: 1,
      title: 'Add health score tracking to dashboard',
      repo: 'frontend-applications/navigation',
      author: 'You',
      status: 'ready' as const,
      comments: 3,
      reviewers: ['Scott Miller', 'Dave Shawley'],
      createdAt: '2 hours ago',
      branch: 'feature/health-tracking',
    },
    {
      id: 2,
      title: 'Fix deployment status indicator',
      repo: 'platform/deployment-service',
      author: 'You',
      status: 'pending' as const,
      comments: 0,
      reviewers: ['Gavin Roy'],
      createdAt: '5 hours ago',
      branch: 'bugfix/status-indicator',
    },
    {
      id: 3,
      title: 'Update authentication flow',
      repo: 'security/auth-service',
      author: 'You',
      status: 'changes-requested' as const,
      comments: 7,
      reviewers: ['Jim Fitzpatrick', 'Scott Miller'],
      createdAt: '1 day ago',
      branch: 'feature/oauth-updates',
    },
    {
      id: 4,
      title: 'Optimize database queries for reports',
      repo: 'backend/analytics',
      author: 'You',
      status: 'approved' as const,
      comments: 2,
      reviewers: ['Dave Shawley'],
      createdAt: '2 days ago',
      branch: 'perf/query-optimization',
    },
  ]

  const statusConfig = {
    ready: {
      label: 'Ready for Review',
      color: 'blue' as const,
      icon: GitPullRequest,
    },
    pending: { label: 'Pending Review', color: 'yellow' as const, icon: Clock },
    'changes-requested': {
      label: 'Changes Requested',
      color: 'red' as const,
      icon: MessageSquare,
    },
    approved: { label: 'Approved', color: 'green' as const, icon: CheckCircle },
  }

  return (
    <Card className={'p-6'}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className={'text-lg text-primary'}>My Pull Requests</h3>
        <span className={'text-sm text-secondary'}>
          {pullRequests.length} open
        </span>
      </div>

      <div className="space-y-3">
        {pullRequests.map((pr) => {
          const config = statusConfig[pr.status]
          const StatusIcon = config.icon

          return (
            <div
              key={pr.id}
              className={`rounded-lg border p-4 transition-colors ${'border-input bg-background hover:border-secondary'}`}
            >
              <div className="flex items-start gap-3">
                <GitPullRequest
                  className={`mt-0.5 h-5 w-5 flex-shrink-0 ${'text-tertiary'}`}
                />
                <div className="min-w-0 flex-1">
                  <div className={'mb-1 font-medium text-primary'}>
                    {pr.title}
                  </div>
                  <div className={'mb-2 text-sm text-secondary'}>
                    {pr.repo} • {pr.branch}
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <Badge
                      variant={
                        ({
                          blue: 'info',
                          yellow: 'warning',
                          red: 'danger',
                        }[config.color as string] ??
                          'success') as BadgeProps['variant']
                      }
                      className="gap-1.5 rounded-full"
                    >
                      <StatusIcon className="h-3 w-3" />
                      {config.label}
                    </Badge>

                    {pr.comments > 0 && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        <MessageSquare className="h-3 w-3" />
                        {pr.comments}
                      </span>
                    )}

                    <span className="text-xs text-gray-500">
                      {pr.createdAt}
                    </span>
                  </div>

                  {pr.reviewers.length > 0 && (
                    <div className="mt-2 text-xs text-gray-500">
                      Reviewers:{' '}
                      {pr.reviewers.map((reviewer, idx) => (
                        <button
                          type="button"
                          key={idx}
                          onClick={() => onUserSelect?.(reviewer)}
                          className={`hover:text-info/80 text-info ${
                            idx > 0 ? 'ml-1' : ''
                          }`}
                        >
                          {reviewer}
                          {idx < pr.reviewers.length - 1 ? ',' : ''}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
