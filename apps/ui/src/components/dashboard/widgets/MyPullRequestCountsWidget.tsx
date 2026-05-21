import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { GitMerge } from 'lucide-react'

import { getOrgPullRequests } from '@/api/endpoints'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useGithubLogin } from '@/hooks/useGithubLogin'

// fallow-ignore-next-line complexity
export function MyPullRequestCountsWidget() {
  const navigate = useNavigate()
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

  const isLoading = identitiesLoading || openLoading
  const isError = identitiesError || openError
  const openCount = openData?.total ?? 0

  return (
    <Card
      aria-label="View my open pull requests"
      className="hover:border-secondary relative flex h-full cursor-pointer flex-col transition-colors"
      onClick={() => navigate('/projects?view=list&has_my_open_prs=1')}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          navigate('/projects?view=list&has_my_open_prs=1')
        }
      }}
      role="link"
      tabIndex={0}
    >
      <GitMerge className="text-tertiary absolute top-6 right-6 size-9" />
      <CardHeader className="pb-2">
        <CardTitle className="text-secondary font-normal">
          My Open PRs
        </CardTitle>
      </CardHeader>
      <CardContent className="mt-auto">
        {isLoading ? (
          <Skeleton
            aria-label="Loading My Open PRs"
            className="bg-tertiary/40 inline-block h-8 w-20"
            role="status"
          />
        ) : isError ? (
          <p className="text-danger text-sm">Unavailable</p>
        ) : notConnected ? (
          <>
            <p className="text-tertiary text-3xl">—</p>
            <a
              className="text-action mt-1 block text-xs hover:underline"
              href="/settings/connections"
              onClick={(event) => event.stopPropagation()}
            >
              Connect GitHub
            </a>
          </>
        ) : (
          <p className="text-primary text-3xl">{openCount.toLocaleString()}</p>
        )}
      </CardContent>
    </Card>
  )
}
