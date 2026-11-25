import { useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getOrgPendingDeployPullRequests } from '@/api/endpoints'
import { PendingDeployList } from '@/components/dashboard/widgets/PendingDeployList'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'

const MINE = '@me'
// The API returns at most this many rows (PENDING_DEPLOY_LIMIT).
const PENDING_DEPLOY_LIMIT = 200

/**
 * Merged pull requests not yet deployed to a terminal environment.
 * ``?author=@me`` (the Slack Home link) shows only the caller's PRs.
 */
export function MergedNotDeployedReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [searchParams, setSearchParams] = useSearchParams()
  const author = searchParams.get('author') ?? undefined

  const { data, isError, isLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPendingDeployPullRequests(orgSlug, { author }, signal),
    queryKey: ['pending-deploy-report', orgSlug, author],
    staleTime: 60_000,
  })
  const { projectsById } = useProjectsSlimMap(orgSlug)
  const prs = data?.data ?? []

  const setMine = (mine: boolean) =>
    setSearchParams(mine ? { author: MINE } : {}, { replace: true })

  return (
    <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
      <div className="border-tertiary flex items-center gap-3 border-b px-4 py-3">
        {[
          { label: 'All', mine: false },
          { label: 'Mine', mine: true },
        ].map((o) => (
          <button
            aria-pressed={(author === MINE) === o.mine}
            className="text-tertiary hover:text-primary aria-pressed:text-primary aria-pressed:border-action border-b-2 border-transparent pb-0.5 text-xs transition-colors"
            key={o.label}
            onClick={() => setMine(o.mine)}
            type="button"
          >
            {o.label}
          </button>
        ))}
        {!isLoading && !isError && (
          <span className="text-tertiary ml-auto text-xs">{prs.length}</span>
        )}
      </div>
      <div className="p-4">
        <PendingDeployList
          emptyMessage={
            data?.github_identity_missing
              ? 'No GitHub identity connected.'
              : 'Every merged pull request has reached a terminal environment.'
          }
          isError={isError}
          isLoading={isLoading}
          projectsById={projectsById}
          prs={prs}
          showAuthor={author !== MINE}
        />
        {prs.length >= PENDING_DEPLOY_LIMIT && (
          <p className="text-tertiary mt-3 text-xs">
            Showing the oldest {PENDING_DEPLOY_LIMIT}. Deploy or filter to see
            more.
          </p>
        )}
      </div>
    </div>
  )
}
