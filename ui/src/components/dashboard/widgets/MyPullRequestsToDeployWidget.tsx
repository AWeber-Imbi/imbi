import { useQuery } from '@tanstack/react-query'

import { getOrgPendingDeployPullRequests } from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useGithubLogin } from '@/hooks/useGithubLogin'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'

import { PendingDeployList } from './PendingDeployList'

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
        Merged pull requests whose project has not been deployed to a terminal
        environment since the merge.
      </p>

      <div aria-busy={isLoading} className="min-h-0 flex-1 overflow-y-auto">
        {!isLoading && !isError && notConnected ? (
          <div className="text-secondary py-6 text-center text-sm">
            <p className="mb-2">No GitHub identity connected.</p>
            <a
              className="text-action text-xs hover:underline"
              href="/settings/connections"
            >
              Connect GitHub
            </a>
          </div>
        ) : (
          <PendingDeployList
            emptyMessage="Everything you merged has reached a terminal environment."
            isError={isError}
            isLoading={isLoading}
            projectsById={projectsById}
            prs={prs}
          />
        )}
      </div>
    </Card>
  )
}
