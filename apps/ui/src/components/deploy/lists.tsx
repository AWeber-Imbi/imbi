import { Check, ExternalLink } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { DeploymentCommit, DeploymentRef } from '@/types'

export function BranchList({
  activeBranch,
  branches,
  isError,
  isLoading,
  onRetry,
  onSelect,
}: {
  activeBranch: null | string
  branches: DeploymentRef[]
  isError: boolean
  isLoading: boolean
  onRetry: () => void
  onSelect: (name: string) => void
}) {
  if (isError)
    return (
      <div className="border-danger bg-danger/10 text-danger rounded-md border px-3 py-2 text-sm">
        Failed to load branches.{' '}
        <Button className="ml-2" onClick={onRetry} size="sm" variant="ghost">
          Retry
        </Button>
      </div>
    )
  if (isLoading)
    return (
      <ul
        aria-busy="true"
        aria-label="Loading branches"
        className="border-secondary rounded-md border"
      >
        {Array.from({ length: 6 }, (_, i) => (
          <li
            aria-hidden="true"
            className="border-tertiary flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
            key={i}
          >
            <Skeleton className="h-3 flex-1" />
          </li>
        ))}
      </ul>
    )
  if (branches.length === 0)
    return (
      <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
        No branches.
      </p>
    )
  return (
    <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
      {branches.map((b) => {
        const active = b.name === activeBranch
        return (
          <li
            className={cn(
              'border-b border-tertiary last:border-b-0',
              active && 'bg-action/5',
            )}
            key={b.name}
          >
            <button
              className="flex w-full min-w-0 cursor-pointer items-center gap-2 px-3 py-2 text-left"
              onClick={() => onSelect(b.name)}
              type="button"
            >
              <span className="min-w-0 flex-1 truncate text-sm">{b.name}</span>
              {b.pr_number ? (
                <Badge variant="outline">#{b.pr_number}</Badge>
              ) : null}
              {active ? <Check className="text-action size-4" /> : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export function CommitList({
  commits,
  current,
  isError,
  isLoading,
  onRetry,
  onSelect,
  selectedSha,
}: {
  commits: DeploymentCommit[]
  current: null | string
  isError: boolean
  isLoading: boolean
  onRetry: () => void
  onSelect: (commit: DeploymentCommit) => void
  selectedSha: null | string
}) {
  if (isError)
    return (
      <div className="border-danger bg-danger/10 text-danger rounded-md border px-3 py-2 text-sm">
        Failed to load commits.{' '}
        <Button className="ml-2" onClick={onRetry} size="sm" variant="ghost">
          Retry
        </Button>
      </div>
    )
  if (isLoading)
    return (
      <ul
        aria-busy="true"
        aria-label="Loading commits"
        className="border-secondary rounded-md border"
      >
        {Array.from({ length: 6 }, (_, i) => (
          <li
            aria-hidden="true"
            className="border-tertiary flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
            key={i}
          >
            <Skeleton className="h-3 w-12 shrink-0" />
            <Skeleton className="h-3 flex-1" />
            <Skeleton className="h-3 w-16 shrink-0" />
          </li>
        ))}
      </ul>
    )
  if (commits.length === 0)
    return (
      <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
        No commits available.
      </p>
    )
  return (
    <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
      {commits.map((c) => {
        const active = c.sha === selectedSha
        const isCurrent = current ? c.sha.startsWith(current) : false
        return (
          <li
            className={cn(
              'flex min-w-0 items-center gap-3 border-b border-tertiary px-3 py-2 last:border-b-0',
              active && 'bg-action/5',
            )}
            key={c.sha}
          >
            <button
              className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left"
              onClick={() => onSelect(c)}
              type="button"
            >
              <span className="shrink-0 font-mono text-xs">{c.short_sha}</span>
              <span className="min-w-0 flex-1 truncate text-sm">
                {c.message}
              </span>
              <span className="text-tertiary shrink-0 text-xs">{c.author}</span>
              {c.is_head ? <Badge variant="outline">HEAD</Badge> : null}
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action size-4" /> : null}
            </button>
            {c.url ? (
              <a
                aria-label="View commit on GitHub"
                className="text-tertiary hover:text-primary"
                href={c.url}
                rel="noopener"
                target="_blank"
              >
                <ExternalLink className="size-3.5" />
              </a>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

export function TagList({
  current,
  isError,
  isLoading,
  onRetry,
  onSelect,
  selectedSha,
  tags,
}: {
  current: null | string
  isError: boolean
  isLoading: boolean
  onRetry: () => void
  onSelect: (tag: DeploymentRef) => void
  selectedSha: null | string
  tags: DeploymentRef[]
}) {
  if (isError)
    return (
      <div className="border-danger bg-danger/10 text-danger rounded-md border px-3 py-2 text-sm">
        Failed to load tags.{' '}
        <Button className="ml-2" onClick={onRetry} size="sm" variant="ghost">
          Retry
        </Button>
      </div>
    )
  if (isLoading)
    return (
      <ul
        aria-busy="true"
        aria-label="Loading tags"
        className="border-secondary rounded-md border"
      >
        {Array.from({ length: 5 }, (_, i) => (
          <li
            aria-hidden="true"
            className="border-tertiary flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
            key={i}
          >
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-12" />
          </li>
        ))}
      </ul>
    )
  if (tags.length === 0)
    return (
      <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
        No tags available.
      </p>
    )
  return (
    <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
      {tags.map((t) => {
        const active = t.sha === selectedSha
        const isCurrent = t.name === current
        return (
          <li
            className={cn(
              'flex items-center justify-between border-b border-tertiary px-3 py-2 last:border-b-0',
              active && 'bg-action/5',
            )}
            key={t.name}
          >
            <button
              className="flex flex-1 cursor-pointer items-center gap-3 text-left"
              onClick={() => onSelect(t)}
              type="button"
            >
              <span className="font-mono text-sm">{t.name}</span>
              <span className="text-tertiary font-mono text-xs">
                {t.sha.slice(0, 7)}
              </span>
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action size-4" /> : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
