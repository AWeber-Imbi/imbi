import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  ExternalLink,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  RefreshCw,
} from 'lucide-react'

import { getProjectPullRequests } from '@/api/endpoints'
import { DiffBar } from '@/components/pull-requests/DiffBar'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { UserDisplay } from '@/components/ui/user-display'
import { useLoginToEmail } from '@/hooks/useLoginToEmail'
import { relTime } from '@/lib/formatDate'
import type { PullRequest } from '@/types'

interface Props {
  orgSlug: string
  projectId: string
}

type StateFilter = 'all' | 'closed' | 'draft' | 'merged' | 'open'

// fallow-ignore-next-line complexity
export function ProjectPullRequestsTab({ orgSlug, projectId }: Props) {
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [search, setSearch] = useState('')

  const {
    data: openData,
    isError: openError,
    isFetching: openFetching,
    refetch: refetchOpen,
  } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      getProjectPullRequests(
        orgSlug,
        projectId,
        { limit: 100, state: 'open' },
        signal,
      ),
    queryKey: ['project-prs', orgSlug, projectId, 'open'],
    staleTime: 60_000,
  })

  const {
    data: closedData,
    isError: closedError,
    isFetching: closedFetching,
    refetch: refetchClosed,
  } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) =>
      getProjectPullRequests(
        orgSlug,
        projectId,
        { limit: 100, state: 'closed' },
        signal,
      ),
    queryKey: ['project-prs', orgSlug, projectId, 'closed'],
    staleTime: 60_000,
  })

  const { displayNames, loginToEmail } = useLoginToEmail()

  const isLoading = openFetching || closedFetching
  const hasError = openError || closedError

  // fallow-ignore-next-line complexity
  const allPRs = useMemo(() => {
    const open = openData?.data ?? []
    const closed = closedData?.data ?? []
    return [...open, ...closed].sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
  }, [openData, closedData])

  // fallow-ignore-next-line complexity
  const counts = useMemo(() => {
    let openCount = 0
    let draftCount = 0
    let mergedCount = 0
    let closedCount = 0
    for (const pr of allPRs) {
      if (pr.draft) draftCount++
      else if (pr.merged) mergedCount++
      else if (pr.state === 'open') openCount++
      else closedCount++
    }
    return {
      all: allPRs.length,
      closed: closedCount,
      draft: draftCount,
      merged: mergedCount,
      open: openCount,
    }
  }, [allPRs])

  // fallow-ignore-next-line complexity
  const filtered = useMemo(() => {
    let prs = allPRs
    switch (stateFilter) {
      case 'closed':
        prs = prs.filter((pr) => pr.state === 'closed' && !pr.merged)
        break
      case 'draft':
        prs = prs.filter((pr) => pr.draft)
        break
      case 'merged':
        prs = prs.filter((pr) => pr.merged)
        break
      case 'open':
        prs = prs.filter((pr) => pr.state === 'open' && !pr.draft)
        break
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      prs = prs.filter(
        (pr) =>
          pr.title.toLowerCase().includes(q) ||
          pr.author.toLowerCase().includes(q) ||
          String(pr.pr_number).includes(q),
      )
    }
    return prs
  }, [allPRs, stateFilter, search])

  function handleRefresh() {
    void refetchOpen()
    void refetchClosed()
  }

  const filterOptions: [StateFilter, string][] = [
    ['all', `All ${counts.all}`],
    ['open', `Open ${counts.open}`],
    ['draft', `Draft ${counts.draft}`],
    ['merged', `Merged ${counts.merged}`],
    ['closed', `Closed ${counts.closed}`],
  ]

  return (
    <Card>
      {/* Toolbar */}
      <div className="border-border flex flex-wrap items-center gap-4 border-b px-4 py-3">
        <div className="flex items-center gap-0.5">
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
        <div className="flex flex-1 items-center justify-end gap-2">
          <input
            className="border-input bg-background text-primary focus:ring-action h-8 w-56 rounded border px-3 text-sm focus:ring-1 focus:outline-none"
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by title, author, or #"
            type="text"
            value={search}
          />
          <span className="text-tertiary text-xs">
            {filtered.length} of {counts.all}
          </span>
          <button
            aria-label="Refresh pull requests"
            className="text-tertiary hover:text-primary rounded p-1.5 transition-colors"
            disabled={isLoading}
            onClick={handleRefresh}
            type="button"
          >
            <RefreshCw
              className={`size-4 ${isLoading ? 'animate-spin' : ''}`}
            />
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-border border-b">
              <th className="text-tertiary w-16 px-4 py-2 text-left text-xs font-medium tracking-wide uppercase">
                #
              </th>
              <th className="text-tertiary px-4 py-2 text-left text-xs font-medium tracking-wide uppercase">
                Title
              </th>
              <th className="text-tertiary w-24 px-4 py-2 text-center text-xs font-medium tracking-wide uppercase">
                State
              </th>
              <th className="text-tertiary w-40 px-4 py-2 text-center text-xs font-medium tracking-wide uppercase">
                Author
              </th>
              <th className="text-tertiary w-14 px-4 py-2 text-center text-xs font-medium tracking-wide uppercase">
                Files
              </th>
              <th className="text-tertiary w-36 px-4 py-2 text-center text-xs font-medium tracking-wide uppercase">
                Diff
              </th>
              <th className="text-tertiary w-20 px-4 py-2 text-right text-xs font-medium tracking-wide uppercase">
                Updated
              </th>
            </tr>
          </thead>
          <tbody>
            {hasError ? (
              <tr>
                <td className="px-4 py-8 text-center" colSpan={7}>
                  <div className="text-danger text-sm">
                    Failed to load pull requests.
                  </div>
                  <button
                    className="text-action mt-2 text-xs hover:underline"
                    onClick={handleRefresh}
                    type="button"
                  >
                    Retry
                  </button>
                </td>
              </tr>
            ) : isLoading && allPRs.length === 0 ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr className="border-border border-b" key={i}>
                  <td className="px-4 py-3" colSpan={7}>
                    <div className="bg-tertiary/30 h-4 animate-pulse rounded" />
                  </td>
                </tr>
              ))
            ) : filtered.length === 0 ? (
              <tr>
                <td
                  className="text-tertiary px-4 py-12 text-center"
                  colSpan={7}
                >
                  No pull requests found.
                </td>
              </tr>
            ) : (
              filtered.map((pr) => (
                <PrRow
                  displayNames={displayNames}
                  key={pr.pr_id}
                  loginToEmail={loginToEmail}
                  pr={pr}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// fallow-ignore-next-line complexity
function PrRow({
  displayNames,
  loginToEmail,
  pr,
}: {
  displayNames: Map<string, string>
  loginToEmail: Map<string, string>
  pr: PullRequest
}) {
  const PrIcon = pr.merged
    ? GitMerge
    : pr.state === 'closed'
      ? GitPullRequestClosed
      : GitPullRequest
  const iconColor = pr.merged
    ? 'text-info'
    : pr.state === 'closed'
      ? 'text-danger'
      : pr.draft
        ? 'text-tertiary'
        : 'text-success'
  const email = loginToEmail.get(pr.author)

  return (
    <tr className="border-border hover:bg-secondary/30 border-b transition-colors last:border-b-0">
      <td className="px-4 py-3">
        <span className="text-tertiary flex items-center gap-1.5 text-xs">
          <PrIcon className={`size-3.5 shrink-0 ${iconColor}`} />
          {pr.pr_number}
        </span>
      </td>
      <td className="max-w-0 px-4 py-3">
        <a
          className="text-primary hover:text-action inline-flex max-w-full items-center gap-1.5 font-medium transition-colors"
          href={pr.url}
          rel="noreferrer"
          target="_blank"
        >
          <span className="truncate">{pr.title}</span>
          <ExternalLink className="text-tertiary size-3 shrink-0" />
        </a>
      </td>
      <td className="px-4 py-3">
        <PrStateBadge pr={pr} />
      </td>
      <td className="px-4 py-3 text-center">
        <UserDisplay
          displayNames={email ? displayNames : undefined}
          email={email ?? pr.author}
          linkToProfile={!!email}
          textClassName="text-sm"
        />
      </td>
      <td className="text-secondary px-4 py-3 text-right">
        {pr.changed_files}
      </td>
      <td className="px-4 py-3 text-right">
        <DiffBar additions={pr.additions} deletions={pr.deletions} />
      </td>
      <td className="text-tertiary px-4 py-3 text-right text-xs tabular-nums">
        {relTime(pr.updated_at)}
      </td>
    </tr>
  )
}

function PrStateBadge({ pr }: { pr: PullRequest }) {
  if (pr.draft) return <Badge variant="neutral">Draft</Badge>
  if (pr.merged) return <Badge variant="info">Merged</Badge>
  if (pr.state === 'open') return <Badge variant="success">Open</Badge>
  return <Badge variant="danger">Closed</Badge>
}
