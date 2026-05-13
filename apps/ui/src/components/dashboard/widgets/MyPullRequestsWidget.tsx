import { CheckCircle, Clock, GitPullRequest, MessageSquare } from 'lucide-react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

interface MyPullRequestsWidgetProps {
  onUserSelect?: (userName: string) => void
}

export function MyPullRequestsWidget({
  onUserSelect,
}: MyPullRequestsWidgetProps) {
  const pullRequests = [
    {
      author: 'You',
      branch: 'feature/health-tracking',
      comments: 3,
      createdAt: '2 hours ago',
      id: 1,
      repo: 'frontend-applications/navigation',
      reviewers: ['Scott Miller', 'Dave Shawley'],
      status: 'ready' as const,
      title: 'Add health score tracking to dashboard',
    },
    {
      author: 'You',
      branch: 'bugfix/status-indicator',
      comments: 0,
      createdAt: '5 hours ago',
      id: 2,
      repo: 'platform/deployment-service',
      reviewers: ['Gavin Roy'],
      status: 'pending' as const,
      title: 'Fix deployment status indicator',
    },
    {
      author: 'You',
      branch: 'feature/oauth-updates',
      comments: 7,
      createdAt: '1 day ago',
      id: 3,
      repo: 'security/auth-service',
      reviewers: ['Jim Fitzpatrick', 'Scott Miller'],
      status: 'changes-requested' as const,
      title: 'Update authentication flow',
    },
    {
      author: 'You',
      branch: 'perf/query-optimization',
      comments: 2,
      createdAt: '2 days ago',
      id: 4,
      repo: 'backend/analytics',
      reviewers: ['Dave Shawley'],
      status: 'approved' as const,
      title: 'Optimize database queries for reports',
    },
  ]

  const statusConfig = {
    approved: { color: 'green' as const, icon: CheckCircle, label: 'Approved' },
    'changes-requested': {
      color: 'red' as const,
      icon: MessageSquare,
      label: 'Changes Requested',
    },
    pending: { color: 'yellow' as const, icon: Clock, label: 'Pending Review' },
    ready: {
      color: 'blue' as const,
      icon: GitPullRequest,
      label: 'Ready for Review',
    },
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-primary text-lg">My Pull Requests</h3>
        <span className="text-secondary text-sm">
          {pullRequests.length} open
        </span>
      </div>

      <div className="space-y-3">
        {pullRequests.map((pr) => {
          const config = statusConfig[pr.status]
          const StatusIcon = config.icon

          return (
            <div
              className="border-input bg-background hover:border-secondary rounded-lg border p-4 transition-colors"
              key={pr.id}
            >
              <div className="flex items-start gap-3">
                <GitPullRequest className="text-tertiary mt-0.5 size-5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-primary mb-1 font-medium">
                    {pr.title}
                  </div>
                  <div className="text-secondary mb-2 text-sm">
                    {pr.repo} • {pr.branch}
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <Badge
                      className="gap-1.5 rounded-full"
                      variant={
                        ({
                          blue: 'info',
                          red: 'danger',
                          yellow: 'warning',
                        }[config.color as string] ??
                          'success') as BadgeProps['variant']
                      }
                    >
                      <StatusIcon className="size-3" />
                      {config.label}
                    </Badge>

                    {pr.comments > 0 && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        <MessageSquare className="size-3" />
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
                          className={`text-info hover:text-info/80 ${
                            idx > 0 ? 'ml-1' : ''
                          }`}
                          key={idx}
                          onClick={() => onUserSelect?.(reviewer)}
                          type="button"
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
