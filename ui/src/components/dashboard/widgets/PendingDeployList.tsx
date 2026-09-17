import { Link } from 'react-router-dom'

import { ChevronRight, GitMerge } from 'lucide-react'

import type { ProjectListItem } from '@/api/endpoints'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import type { PendingDeployPullRequest } from '@/types'

const DAY_MS = 86_400_000

interface PendingDeployListProps {
  emptyMessage: string
  isError: boolean
  isLoading: boolean
  projectsById: Map<string, ProjectListItem>
  prs: PendingDeployPullRequest[]
  /** Show the PR author on each row (for org-wide views). */
  showAuthor?: boolean
}

/**
 * The scrolling body shared by the "PRs to deploy" widgets: skeletons
 * while loading, an error/empty notice, or one row per pending PR.
 */
export function PendingDeployList({
  emptyMessage,
  isError,
  isLoading,
  projectsById,
  prs,
  showAuthor = false,
}: PendingDeployListProps) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <PrRowSkeleton key={i} />
        ))}
      </div>
    )
  }
  if (isError) {
    return (
      <div className="text-danger py-6 text-center text-sm">Unavailable</div>
    )
  }
  if (prs.length === 0) {
    return (
      <div className="text-secondary py-6 text-center text-sm">
        {emptyMessage}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {prs.map((pr) => (
        <PrRow
          key={pr.pr_id}
          pr={pr}
          projectsById={projectsById}
          showAuthor={showAuthor}
        />
      ))}
    </div>
  )
}

function PrRow({
  pr,
  projectsById,
  showAuthor,
}: {
  pr: PendingDeployPullRequest
  projectsById: Map<string, ProjectListItem>
  showAuthor: boolean
}) {
  const project = projectsById.get(pr.project_id)
  const repoLabel = project ? `${project.team.slug}/${project.slug}` : undefined
  const daysWaiting = Math.max(
    0,
    Math.floor((Date.now() - new Date(pr.merged_at).getTime()) / DAY_MS),
  )

  return (
    <Link
      className="border-input bg-background hover:border-secondary flex w-full items-start gap-3 rounded-lg border p-3 transition-colors"
      to={`/projects/${pr.project_id}/deployments`}
    >
      <GitMerge className="mt-0.5 size-5 shrink-0 text-purple-500" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-1.5">
          <span className="text-primary truncate font-medium">{pr.title}</span>
          <span className="text-tertiary shrink-0 text-xs">
            #{pr.pr_number}
          </span>
        </div>
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          {repoLabel && (
            <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
              {repoLabel}
            </code>
          )}
          {showAuthor && (
            <span className="text-secondary text-xs">{pr.author}</span>
          )}
          <span className="bg-warning/10 text-warning inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">
            {daysWaiting === 0
              ? 'Merged today'
              : `Waiting ${daysWaiting} day${daysWaiting === 1 ? '' : 's'}`}
          </span>
        </div>
        <div className="text-tertiary text-xs">
          Merged <RelativeTime tooltip={false} value={pr.merged_at} />
          {' · '}
          Last terminal deploy{' '}
          <RelativeTime tooltip={false} value={pr.last_deployed_at} />
        </div>
      </div>
      <ChevronRight className="text-tertiary mt-0.5 size-4 shrink-0" />
    </Link>
  )
}

function PrRowSkeleton() {
  return (
    <div className="border-input bg-background flex items-start gap-3 rounded-lg border p-3">
      <Sk circle h={20} w={20} />
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-baseline gap-1.5">
          <Sk line w="60%" />
          <Sk line w={24} />
        </div>
        <div className="mb-2 flex items-center gap-1.5">
          <Sk h={18} r={6} w={72} />
          <Sk h={18} r={9999} w={96} />
        </div>
        <Sk line w="50%" />
      </div>
      <Sk className="mt-0.5" h={16} w={16} />
    </div>
  )
}
