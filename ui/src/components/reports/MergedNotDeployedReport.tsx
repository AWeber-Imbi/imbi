import { useSearchParams } from 'react-router-dom'

import { useInfiniteQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'

import { getOrgPendingDeployPullRequests } from '@/api/endpoints'
import { PendingDeployList } from '@/components/dashboard/widgets/PendingDeployList'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import type { PendingDeployResponse } from '@/types'

const MINE = '@me'
const PAGE_SIZE = 200

/**
 * Merged pull requests not yet deployed to a terminal environment.
 * ``?author=@me`` (the Slack Home link) shows only the caller's PRs.
 * Projects with no terminal deploy in the window are hidden unless
 * ``?stale=show``.
 */
export function MergedNotDeployedReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [searchParams, setSearchParams] = useSearchParams()
  const author = searchParams.get('author') ?? undefined
  const showStale = searchParams.get('stale') === 'show'

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isFetchNextPageError,
    isLoading,
  } = useInfiniteQuery<
    PendingDeployResponse,
    Error,
    InfiniteData<PendingDeployResponse>,
    readonly unknown[],
    number
  >({
    enabled: !!orgSlug,
    getNextPageParam: (lastPage, _pages, lastPageParam) => {
      const nextOffset = lastPageParam + lastPage.data.length
      return nextOffset < (lastPage.total ?? 0) ? nextOffset : undefined
    },
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      getOrgPendingDeployPullRequests(
        orgSlug,
        {
          author,
          include_stale: showStale,
          limit: PAGE_SIZE,
          offset: pageParam,
        },
        signal,
      ),
    queryKey: ['pending-deploy-report', orgSlug, author, showStale],
    staleTime: 60_000,
  })
  const { projectsById } = useProjectsSlimMap(orgSlug)
  const prs = data?.pages.flatMap((p) => p.data) ?? []
  const first = data?.pages[0]
  // A failed next page keeps the loaded rows; only a failed first page
  // replaces the list with the error state.
  const initialError = isError && !data

  const setParam = (key: string, value: null | string) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === null) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )

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
            onClick={() => setParam('author', o.mine ? MINE : null)}
            type="button"
          >
            {o.label}
          </button>
        ))}
        <button
          aria-pressed={showStale}
          className="text-tertiary hover:text-primary aria-pressed:text-primary ml-auto text-xs transition-colors"
          onClick={() => setParam('stale', showStale ? null : 'show')}
          title="Show projects with no terminal deploy in the last 90 days"
          type="button"
        >
          Show stale projects
        </button>
        {!isLoading && !initialError && (
          <span className="text-tertiary text-xs">
            {first?.total ?? prs.length}
          </span>
        )}
      </div>
      <div className="p-4">
        <PendingDeployList
          emptyMessage={
            first?.github_identity_missing
              ? 'No GitHub identity connected.'
              : 'Every merged pull request has reached a terminal environment.'
          }
          isError={initialError}
          isLoading={isLoading}
          projectsById={projectsById}
          prs={prs}
          showAuthor={author !== MINE}
        />
        {hasNextPage && (
          <div className="mt-3 flex items-center justify-center gap-3">
            {isFetchNextPageError && (
              <span className="text-danger text-xs">
                Could not load more pull requests.
              </span>
            )}
            <Button
              disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
              size="sm"
              variant="outline"
            >
              Load more
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
