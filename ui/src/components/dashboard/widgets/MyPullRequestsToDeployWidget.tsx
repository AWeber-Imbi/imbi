import { useQuery } from '@tanstack/react-query'
import { ChevronRight, GitMerge } from 'lucide-react'

import {
  getOrgPendingDeployPullRequests,
  type ProjectListItem,
} from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useGithubLogin } from '@/hooks/useGithubLogin'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import type { PendingDeployPullRequest } from '@/types'

const DAY_MS = 86_400_000

// fallow-ignore-next-line complexity
export function MyPullRequestsToDeployWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const {
    hasIdentity,
    isError: identitiesError,
    isLoading: identitiesLoading,
    login,
    notConnected,
  } = useGithubLogin()

  const {
    data,
    isError: prsError,
    isLoading: prsLoading,
  } = useQuery({
    enabled: hasIdentity && !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPendingDeployPullRequests(orgSlug, { author: login }, signal),
    queryKey: ['my-prs-to-deploy', orgSlug, login],
    staleTime: 60_000,
  })

  const { projectsById } = useProjectsSlimMap(orgSlug)

  const prs = data?.data ?? []
  const isLoading = identitiesLoading || prsLoading
  const isError = identitiesError || prsError

  return (
    <Card className="flex h-150 flex-col p-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-primary text-lg">My PRs to Deploy</h3>
        {!isLoading && !isError && prs.length > 0 && (
          <span className="text-tertiary text-sm">{prs.length}</span>
        )}
      </div>
      <p className="text-tertiary mb-3 text-xs">
        Merged pull requests whose project has not been deployed to production
        since the merge.
      </p>

      <div aria-busy={isLoading} className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <PrRowSkeleton key={i} />
            ))}
          </div>
        ) : isError ? (
          <div className="text-danger py-6 text-center text-sm">
            Unavailable
          </div>
        ) : notConnected ? (
          <div className="text-secondary py-6 text-center text-sm">
            <p className="mb-2">No GitHub identity connected.</p>
            <a
              className="text-action text-xs hover:underline"
              href="/settings/connections"
            >
              Connect GitHub
            </a>
          </div>
        ) : prs.length === 0 ? (
          <div className="text-secondary py-6 text-center text-sm">
            Everything you merged is in production.
          </div>
        ) : (
          <div className="space-y-2">
            {prs.map((pr) => (
              <PrRow key={pr.pr_id} pr={pr} projectsById={projectsById} />
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

function PrRow({
  pr,
  projectsById,
}: {
  pr: PendingDeployPullRequest
  projectsById: Map<string, ProjectListItem>
}) {
  const project = projectsById.get(pr.project_id)
  const repoLabel = project ? `${project.team.slug}/${project.slug}` : undefined
  const daysWaiting = Math.max(
    0,
    Math.floor((Date.now() - new Date(pr.merged_at).getTime()) / DAY_MS),
  )

  return (
    <a
      className="border-input bg-background hover:border-secondary flex w-full items-start gap-3 rounded-lg border p-3 transition-colors"
      href={pr.url}
      rel="noreferrer"
      target="_blank"
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
          <span className="bg-warning/10 text-warning inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">
            {daysWaiting === 0
              ? 'Merged today'
              : `Waiting ${daysWaiting} day${daysWaiting === 1 ? '' : 's'}`}
          </span>
        </div>
        <div className="text-tertiary text-xs">
          Merged <RelativeTime tooltip={false} value={pr.merged_at} />
          {' · '}
          Last production deploy{' '}
          <RelativeTime tooltip={false} value={pr.last_deployed_at} />
        </div>
      </div>
      <ChevronRight className="text-tertiary mt-0.5 size-4 shrink-0" />
    </a>
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
