import { GitPullRequest, Clock, MessageSquare, CheckCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'

interface MyPullRequestsWidgetProps {
  isDarkMode: boolean
  onUserSelect?: (userName: string) => void
}

export function MyPullRequestsWidget({ isDarkMode, onUserSelect }: MyPullRequestsWidgetProps) {
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
      branch: 'feature/health-tracking'
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
      branch: 'bugfix/status-indicator'
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
      branch: 'feature/oauth-updates'
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
      branch: 'perf/query-optimization'
    }
  ]

  const statusConfig = {
    ready: { label: 'Ready for Review', color: 'blue' as const, icon: GitPullRequest },
    pending: { label: 'Pending Review', color: 'yellow' as const, icon: Clock },
    'changes-requested': { label: 'Changes Requested', color: 'red' as const, icon: MessageSquare },
    approved: { label: 'Approved', color: 'green' as const, icon: CheckCircle }
  }

  return (
    <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-lg ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          My Pull Requests
        </h3>
        <span className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
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
              className={`p-4 rounded-lg border transition-colors ${
                isDarkMode
                  ? 'bg-gray-750 border-gray-600 hover:border-gray-500'
                  : 'bg-white border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex items-start gap-3">
                <GitPullRequest className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className={`font-medium mb-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                    {pr.title}
                  </div>
                  <div className={`text-sm mb-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {pr.repo} • {pr.branch}
                  </div>

                  <div className="flex items-center gap-3 flex-wrap">
                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs ${
                      config.color === 'blue'
                        ? isDarkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-100 text-blue-700'
                        : config.color === 'yellow'
                          ? isDarkMode ? 'bg-yellow-900/30 text-yellow-400' : 'bg-yellow-100 text-yellow-700'
                          : config.color === 'red'
                            ? isDarkMode ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-700'
                            : isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-100 text-green-700'
                    }`}>
                      <StatusIcon className="w-3 h-3" />
                      {config.label}
                    </span>

                    {pr.comments > 0 && (
                      <span className="text-xs flex items-center gap-1 text-gray-500">
                        <MessageSquare className="w-3 h-3" />
                        {pr.comments}
                      </span>
                    )}

                    <span className="text-xs text-gray-500">
                      {pr.createdAt}
                    </span>
                  </div>

                  {pr.reviewers.length > 0 && (
                    <div className="mt-2 text-xs text-gray-500">
                      Reviewers: {pr.reviewers.map((reviewer, idx) => (
                        <button
                          type="button"
                          key={idx}
                          onClick={() => onUserSelect?.(reviewer)}
                          className={`${isDarkMode ? 'text-blue-400 hover:text-blue-300' : 'text-[#2A4DD0] hover:text-blue-700'} ${
                            idx > 0 ? 'ml-1' : ''
                          }`}
                        >
                          {reviewer}{idx < pr.reviewers.length - 1 ? ',' : ''}
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
