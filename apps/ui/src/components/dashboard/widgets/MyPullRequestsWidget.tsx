import { useQuery } from '@tanstack/react-query'
import { GitMerge } from 'lucide-react'

import { getMyIdentities, getOrgPullRequests } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { IdentityConnectionResponse } from '@/types'

const GITHUB_PR_PLUGIN_SLUG = 'github-enterprise-cloud'

// fallow-ignore-next-line complexity
export function MyPullRequestsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const {
    data: identities,
    isError: identitiesError,
    isLoading: identitiesLoading,
  } = useQuery({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    staleTime: 0,
  })

  const login = identities ? githubLogin(identities) : undefined
  const hasIdentity = !identitiesLoading && !!login

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
        { author: login, limit: 1, state: 'closed' },
        signal,
      ),
    queryKey: ['my-prs', orgSlug, login, 'closed'],
    staleTime: 60 * 1000,
  })

  const isLoading = identitiesLoading || openLoading || closedLoading
  const isError = identitiesError || openError || closedError
  const notConnected = !identitiesLoading && !login
  const openCount = openData?.total ?? 0
  const closedCount = closedData?.total ?? 0

  return (
    <div className="border-border bg-card rounded-lg border p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-secondary text-sm">My Pull Requests</p>
          {isLoading ? (
            <span
              aria-label="Loading My Pull Requests"
              className="bg-tertiary/40 mt-2 inline-block h-9 w-32 animate-pulse rounded"
              role="status"
            />
          ) : isError ? (
            <p className="text-danger mt-2 text-sm">Unavailable</p>
          ) : notConnected ? (
            <>
              <p className="text-tertiary mt-2 text-3xl">—</p>
              <a
                className="text-action mt-1 block text-xs hover:underline"
                href="/settings/connections"
              >
                Connect GitHub
              </a>
            </>
          ) : (
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-primary text-3xl">
                {openCount.toLocaleString()}
              </span>
              <span className="text-secondary text-sm">Open</span>
              <span className="text-tertiary text-sm">/</span>
              <span className="text-tertiary text-3xl">
                {closedCount.toLocaleString()}
              </span>
              <span className="text-secondary text-sm">Closed</span>
            </div>
          )}
        </div>
        <GitMerge className="text-tertiary size-9 shrink-0" />
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function githubLogin(
  identities: IdentityConnectionResponse[],
): string | undefined {
  const conn = identities.find((i) => i.plugin_slug === GITHUB_PR_PLUGIN_SLUG)
  if (!conn) return undefined
  const login = conn.metadata?.login
  return typeof login === 'string' && login ? login : undefined
}
