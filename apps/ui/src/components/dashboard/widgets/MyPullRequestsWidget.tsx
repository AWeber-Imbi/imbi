import { useEffect, useMemo, useRef, useState } from 'react'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import {
  ChevronRight,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
} from 'lucide-react'

import {
  getMyIdentities,
  getOrgPullRequests,
  getProjects,
} from '@/api/endpoints'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { relTime } from '@/lib/formatDate'
import type {
  IdentityConnectionResponse,
  Project,
  PullRequest,
  PullRequestListResponse,
} from '@/types'

const GITHUB_PR_PLUGIN_SLUG = 'github-enterprise-cloud'
const PAGE_SIZE = 20

type StateFilter = 'closed' | 'merged' | 'open'

// fallow-ignore-next-line complexity
export function MyPullRequestsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [stateFilter, setStateFilter] = useState<StateFilter>('open')
  const sentinelRef = useRef<HTMLDivElement>(null)

  const { data: identities, isLoading: identitiesLoading } = useQuery({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    staleTime: 0,
  })

  const login = identities ? githubLogin(identities) : undefined
  const hasIdentity = !identitiesLoading && !!login
  const notConnected = !identitiesLoading && !login

  const apiState =
    stateFilter === 'open' ? 'open' : ('closed' as 'closed' | 'open')

  const {
    data,
    fetchNextPage,
    hasNextPage,
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
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((s, p) => s + p.data.length, 0)
      return loaded < lastPage.total ? loaded : undefined
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

  const { data: projects } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  const projectsById = useMemo(() => {
    const m = new Map<string, Project>()
    for (const p of projects ?? []) m.set(p.id, p)
    return m
  }, [projects])

  // fallow-ignore-next-line complexity
  const prs = useMemo(() => {
    const flat = data?.pages.flatMap((p) => p.data) ?? []
    if (stateFilter === 'merged') return flat.filter((pr) => pr.merged)
    if (stateFilter === 'closed')
      return flat.filter((pr) => pr.state === 'closed' && !pr.merged)
    return flat
  }, [data, stateFilter])

  const total = data?.pages[0]?.total ?? 0

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage()
        }
      },
      { threshold: 0.1 },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [fetchNextPage, hasNextPage, isFetchingNextPage])

  const isLoading = identitiesLoading || prsLoading

  const filterOptions: [StateFilter, string][] = [
    ['open', 'Open'],
    ['merged', 'Merged'],
    ['closed', 'Closed'],
  ]

  return (
    <Card className="flex h-full flex-col p-6">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-primary text-lg">My Pull Requests</h3>
          {!isLoading && total > 0 && (
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
            onClick={() => setStateFilter(s)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                aria-hidden="true"
                className="bg-tertiary/30 h-20 animate-pulse rounded-lg"
                key={i}
              />
            ))}
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
              {isFetchingNextPage && (
                <div
                  aria-hidden="true"
                  className="bg-tertiary/30 h-16 animate-pulse rounded-lg"
                />
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
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

// fallow-ignore-next-line complexity
function PrRow({
  pr,
  projectsById,
}: {
  pr: PullRequest
  projectsById: Map<string, Project>
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
          {relTime(pr.updated_at)} ago
        </div>
      </div>
      <ChevronRight className="text-tertiary mt-0.5 size-4 shrink-0" />
    </a>
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
