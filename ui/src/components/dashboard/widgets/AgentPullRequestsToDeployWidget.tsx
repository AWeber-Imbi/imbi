import { useQuery } from '@tanstack/react-query'

import { getOrgPendingDeployPullRequests } from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'

import { PendingDeployList } from './PendingDeployList'

export function AgentPullRequestsToDeployWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const { data, isError, isLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPendingDeployPullRequests(orgSlug, { bots: true }, signal),
    queryKey: ['agent-prs-to-deploy', orgSlug],
    staleTime: 60_000,
  })

  const { projectsById } = useProjectsSlimMap(orgSlug)
  const prs = data?.data ?? []

  return (
    <Card className="flex h-150 flex-col p-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-primary text-lg">Agent PRs to Deploy</h3>
        {!isLoading && !isError && prs.length > 0 && (
          <span className="text-tertiary text-sm">{prs.length}</span>
        )}
      </div>
      <p className="text-tertiary mb-3 text-xs">
        Merged pull requests opened by agents and bots whose project has not
        been deployed to a terminal environment since the merge.
      </p>

      <div aria-busy={isLoading} className="min-h-0 flex-1 overflow-y-auto">
        <PendingDeployList
          emptyMessage="Every agent PR has reached a terminal environment."
          isError={isError}
          isLoading={isLoading}
          projectsById={projectsById}
          prs={prs}
          showAuthor
        />
      </div>
    </Card>
  )
}
