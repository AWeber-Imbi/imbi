import { useQuery } from '@tanstack/react-query'

import { getOrgPullRequests } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useGithubLogin } from '@/hooks/useGithubLogin'

// fallow-ignore-next-line complexity
export function MyPullRequestCountsWidget() {
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
    data: openData,
    isError: openError,
    isLoading: openLoading,
  } = useQuery({
    enabled: hasIdentity && !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPullRequests(
        orgSlug,
        { author: login, limit: 1, state: 'open' },
        signal,
      ),
    queryKey: ['my-prs', orgSlug, login, 'open'],
    staleTime: 60 * 1000,
  })

  const {
    data: closedData,
    isError: closedError,
    isLoading: closedLoading,
  } = useQuery({
    enabled: hasIdentity && !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPullRequests(
        orgSlug,
        { author: login, limit: 200, state: 'closed' },
        signal,
      ),
    queryKey: ['my-prs', orgSlug, login, 'closed'],
    staleTime: 60 * 1000,
  })

  const isLoading = identitiesLoading || openLoading || closedLoading
  const isError = identitiesError || openError || closedError
  const openCount = openData?.total ?? 0
  // TODO: replace with a dedicated count endpoint or full pagination so
  // merged/closed totals are accurate beyond the first 200 results.
  const mergedCount = closedData?.data.filter((pr) => pr.merged).length ?? 0
  const closedCount = closedData?.data.filter((pr) => !pr.merged).length ?? 0

  return (
    <div className="border-border bg-card flex h-full flex-col justify-center rounded-lg border p-6">
      <p className="text-secondary text-sm">My Pull Request Counts</p>
      {isLoading ? (
        <span
          aria-label="Loading My Pull Request Counts"
          className="bg-tertiary/40 mt-2 inline-block h-9 w-32 animate-pulse rounded"
          role="status"
        />
      ) : isError ? (
        <p className="text-danger mt-2 text-sm">Unavailable</p>
      ) : notConnected ? (
        <>
          <p className="text-tertiary mt-2 text-2xl">—</p>
          <a
            className="text-action mt-1 block text-xs hover:underline"
            href="/settings/connections"
          >
            Connect GitHub
          </a>
        </>
      ) : (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
          <span className="text-primary text-xl">
            {openCount.toLocaleString()}
          </span>
          <span className="text-secondary text-xs">Open</span>
          <span className="text-tertiary text-xs">/</span>
          <span className="text-xl text-purple-500">
            {mergedCount.toLocaleString()}
          </span>
          <span className="text-secondary text-xs">Merged</span>
          <span className="text-tertiary text-xs">/</span>
          <span className="text-tertiary text-xl">
            {closedCount.toLocaleString()}
          </span>
          <span className="text-secondary text-xs">Closed</span>
        </div>
      )}
    </div>
  )
}
