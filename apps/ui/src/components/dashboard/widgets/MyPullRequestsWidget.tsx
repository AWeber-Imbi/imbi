import { useMemo, useState } from 'react'

import { useInfiniteQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import {
  ChevronRight,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
} from 'lucide-react'

import { getOrgPullRequests, type ProjectListItem } from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useGithubLogin } from '@/hooks/useGithubLogin'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import { relTime } from '@/lib/formatDate'
import type { PullRequest, PullRequestListResponse } from '@/types'

const PAGE_SIZE = 20
const FILTER_KEY = 'imbi-my-prs-filter'

type StateFilter = 'all' | 'closed' | 'merged' | 'open'

// fallow-ignore-next-line complexity
export function MyPullRequestsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [stateFilter, setStateFilter] = useState<StateFilter>(readSavedFilter)

  function handleFilterClick(f: StateFilter) {
    const next = stateFilter === f ? 'all' : f
    setStateFilter(next)
    try {
      localStorage.setItem(FILTER_KEY, next)
    } catch {}
  }

  const {
    hasIdentity,
    isError: identitiesError,
    isLoading: identitiesLoading,
    login,
    notConnected,
  } = useGithubLogin()

  const apiState: 'closed' | 'open' | undefined =
    stateFilter === 'open'
      ? 'open'
      : stateFilter === 'all'
        ? undefined
        : 'closed'

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isError: prsError,
    isFetchingNextPage,
    isLoading: prsLoading,
  } = useInfiniteQuery<
    PullRequestListResponse,
    Error,
    InfiniteData<PullRequestListResponse>,
    readonly unknown[],
    number
  >({
    enabled: hasIdentity && !!orgSlug,
    getNextPageParam: (lastPage, _pages, lastPageParam) => {
      const nextOffset = (lastPageParam ?? 0) + lastPage.data.length
      return nextOffset < lastPage.total ? nextOffset : undefined
    },
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      getOrgPullRequests(
        orgSlug,
        { author: login, limit: PAGE_SIZE, offset: pageParam, state: apiState },
        signal,
      ),
    queryKey: ['my-prs-list', orgSlug, login, apiState],
    staleTime: 60_000,
  })

  const { projectsById } = useProjectsSlimMap(orgSlug)

  // fallow-ignore-next-line complexity
  const prs = useMemo(() => {
    const flat = data?.pages.flatMap((p) => p.data) ?? []
    if (stateFilter === 'merged') return flat.filter((pr) => pr.merged)
    if (stateFilter === 'closed')
      return flat.filter((pr) => pr.state === 'closed' && !pr.merged)
    return flat
  }, [data, stateFilter])

  const total = data?.pages[0]?.total ?? 0
  const isLoading = identitiesLoading || prsLoading
  const isError = identitiesError || prsError

  const { sentinelRef } = useInfiniteScroll({
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  })

  const filterOptions: [StateFilter, string][] = [
    ['open', 'Open'],
    ['merged', 'Merged'],
    ['closed', 'Closed'],
  ]

  return (
    <Card className="flex h-150 flex-col p-6">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-primary text-lg">My Pull Requests</h3>
          {/* TODO: show total for merged/closed once a server-side accurate count is available.
               For now, apiState='closed' covers both states so the total is inaccurate for
               client-side filtered views. */}
          {!isLoading &&
            total > 0 &&
            (stateFilter === 'all' || stateFilter === 'open') && (
              <span className="text-tertiary text-sm">{total}</span>
            )}
        </div>
      </div>

      <div className="mb-3 flex items-center gap-0.5">
        {filterOptions.map(([s, label]) => (
          <button
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              stateFilter === s
                ? 'bg-action text-action-foreground'
                : 'text-secondary hover:text-primary'
            }`}
            key={s}
            onClick={() => handleFilterClick(s)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

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
            No pull requests found.
          </div>
        ) : (
          <div className="space-y-2">
            {prs.map((pr) => (
              <PrRow key={pr.pr_id} pr={pr} projectsById={projectsById} />
            ))}
            <div ref={sentinelRef}>
              {isFetchingNextPage && <PrRowSkeleton />}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

// fallow-ignore-next-line complexity
function PrRow({
  pr,
  projectsById,
}: {
  pr: PullRequest
  projectsById: Map<string, ProjectListItem>
}) {
  const project = projectsById.get(pr.project_id)
  const repoLabel = project ? `${project.team.slug}/${project.slug}` : undefined

  const { Icon, iconClass, stateClass, stateLabel } = prStateAttrs(pr)

  return (
    <a
      className="border-input bg-background hover:border-secondary flex w-full items-start gap-3 rounded-lg border p-3 transition-colors"
      href={pr.url}
      rel="noreferrer"
      target="_blank"
    >
      <Icon className={`mt-0.5 size-5 shrink-0 ${iconClass}`} />
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
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${stateClass}`}
          >
            {stateLabel}
          </span>
          {(pr.additions > 0 || pr.deletions > 0) && (
            <>
              <span className="text-success text-xs">
                +{pr.additions.toLocaleString()}
              </span>
              <span className="text-danger text-xs">
                -{pr.deletions.toLocaleString()}
              </span>
            </>
          )}
        </div>
        <div className="text-tertiary text-xs">
          {(() => {
            const r = relTime(pr.updated_at)
            return r === 'now' ? 'just now' : `${r} ago`
          })()}
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
          <Sk h={18} r={9999} w={48} />
        </div>
        <Sk line w="30%" />
      </div>
      <Sk className="mt-0.5" h={16} w={16} />
    </div>
  )
}

function prStateAttrs(pr: PullRequest) {
  if (pr.draft) {
    return {
      Icon: GitPullRequest,
      iconClass: 'text-tertiary',
      stateClass: 'bg-secondary text-secondary',
      stateLabel: 'Draft',
    }
  }
  if (pr.merged) {
    return {
      Icon: GitMerge,
      iconClass: 'text-purple-500',
      stateClass:
        'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
      stateLabel: 'Merged',
    }
  }
  if (pr.state === 'closed') {
    return {
      Icon: GitPullRequestClosed,
      iconClass: 'text-danger',
      stateClass: 'bg-danger/10 text-danger',
      stateLabel: 'Closed',
    }
  }
  return {
    Icon: GitPullRequest,
    iconClass: 'text-info',
    stateClass: 'bg-info/10 text-info',
    stateLabel: 'Open',
  }
}

// fallow-ignore-next-line complexity
function readSavedFilter(): StateFilter {
  try {
    const v = localStorage.getItem(FILTER_KEY)
    if (v === 'all' || v === 'open' || v === 'merged' || v === 'closed')
      return v
  } catch {}
  return 'all'
}
