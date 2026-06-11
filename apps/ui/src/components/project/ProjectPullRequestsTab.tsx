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
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Sk } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { UserIdentity } from '@/components/ui/user-identity'
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
          <Button
            aria-label="Refresh pull requests"
            className="text-tertiary hover:text-primary size-7"
            disabled={isLoading}
            onClick={handleRefresh}
            size="icon"
            type="button"
            variant="ghost"
          >
            <RefreshCw className={isLoading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow className="border-border hover:bg-transparent">
            <TableHead className="text-tertiary h-auto w-16 py-2 text-xs font-medium tracking-wide uppercase">
              #
            </TableHead>
            <TableHead className="text-tertiary h-auto py-2 text-xs font-medium tracking-wide uppercase">
              Title
            </TableHead>
            <TableHead className="text-tertiary h-auto w-24 py-2 text-center text-xs font-medium tracking-wide uppercase">
              State
            </TableHead>
            <TableHead className="text-tertiary h-auto w-40 py-2 text-center text-xs font-medium tracking-wide uppercase">
              Author
            </TableHead>
            <TableHead className="text-tertiary h-auto w-14 py-2 text-center text-xs font-medium tracking-wide uppercase">
              Files
            </TableHead>
            <TableHead className="text-tertiary h-auto w-36 py-2 text-center text-xs font-medium tracking-wide uppercase">
              Diff
            </TableHead>
            <TableHead className="text-tertiary h-auto w-20 py-2 text-right text-xs font-medium tracking-wide uppercase">
              Updated
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {hasError ? (
            <TableRow className="hover:bg-transparent">
              <TableCell className="px-4 py-8 text-center" colSpan={7}>
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
              </TableCell>
            </TableRow>
          ) : isLoading && allPRs.length === 0 ? (
            Array.from({ length: 5 }, (_, i) => <PrRowSkeleton key={i} />)
          ) : filtered.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell
                className="text-tertiary px-4 py-12 text-center"
                colSpan={7}
              >
                No pull requests found.
              </TableCell>
            </TableRow>
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
        </TableBody>
      </Table>
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
    <TableRow className="border-border hover:bg-secondary/30">
      <TableCell className="px-4 py-3">
        <span className="text-tertiary flex items-center gap-1.5 text-xs">
          <PrIcon className={`size-3.5 shrink-0 ${iconColor}`} />
          {pr.pr_number}
        </span>
      </TableCell>
      <TableCell className="max-w-0 px-4 py-3">
        <a
          className="text-primary hover:text-action inline-flex max-w-full items-center gap-1.5 font-medium transition-colors"
          href={pr.url}
          rel="noreferrer"
          target="_blank"
        >
          <span className="truncate">{pr.title}</span>
          <ExternalLink className="text-tertiary size-3 shrink-0" />
        </a>
      </TableCell>
      <TableCell className="px-4 py-3">
        <PrStateBadge pr={pr} />
      </TableCell>
      <TableCell className="px-4 py-3 text-center">
        <UserIdentity
          actor={pr.author}
          displayNames={email ? displayNames : undefined}
          email={email ?? undefined}
          linkToProfile={!!email}
          size="small"
        />
      </TableCell>
      <TableCell className="text-secondary px-4 py-3 text-right">
        {pr.changed_files}
      </TableCell>
      <TableCell className="px-4 py-3 text-right">
        <DiffBar additions={pr.additions} deletions={pr.deletions} />
      </TableCell>
      <TableCell className="text-tertiary px-4 py-3 text-right text-xs tabular-nums">
        {relTime(pr.updated_at)}
      </TableCell>
    </TableRow>
  )
}

// Footprint-matched skeleton for a single PR row. Mirrors `PrRow`'s 7
// columns: state icon + number · title · state badge · author avatar ·
// files count · diff bar · relative timestamp. Purely presentational.
function PrRowSkeleton() {
  return (
    <TableRow className="border-border hover:bg-transparent">
      <TableCell className="px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Sk circle h={14} w={14} />
          <Sk line w={20} />
        </div>
      </TableCell>
      <TableCell className="px-4 py-3">
        <Sk line w="60%" />
      </TableCell>
      <TableCell className="px-4 py-3">
        <div className="flex justify-center">
          <Sk h={18} r={9999} w={52} />
        </div>
      </TableCell>
      <TableCell className="px-4 py-3">
        <div className="flex items-center justify-center gap-1.5">
          <Sk circle h={20} w={20} />
          <Sk line w={72} />
        </div>
      </TableCell>
      <TableCell className="px-4 py-3 text-right">
        <div className="flex justify-end">
          <Sk line w={20} />
        </div>
      </TableCell>
      <TableCell className="px-4 py-3">
        <div className="flex justify-end">
          <Sk h={6} r={9999} w={88} />
        </div>
      </TableCell>
      <TableCell className="px-4 py-3 text-right">
        <div className="flex justify-end">
          <Sk line w={40} />
        </div>
      </TableCell>
    </TableRow>
  )
}

function PrStateBadge({ pr }: { pr: PullRequest }) {
  if (pr.draft) return <Badge variant="neutral">Draft</Badge>
  if (pr.merged) return <Badge variant="info">Merged</Badge>
  if (pr.state === 'open') return <Badge variant="success">Open</Badge>
  return <Badge variant="danger">Closed</Badge>
}
