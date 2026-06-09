import { Check, ExternalLink } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { RecentCommit } from '@/types'

import { CiStatusDot } from './CiStatusDot'

interface CommitRowProps {
  active: boolean
  commit: RecentCommit
  held: boolean
  idx: number
  onSelect: (sha: string) => void
}

interface ReleaseCommitPickerProps {
  commits: RecentCommit[]
  onSelect: (sha: string) => void
  selectedSha: null | string
}

/**
 * Selectable commit list for the release form. Newest-first; commits newer
 * than the selection dim (they'd be held back). The selected row expands to
 * its full commit message.
 */
export function ReleaseCommitPicker({
  commits,
  onSelect,
  selectedSha,
}: ReleaseCommitPickerProps) {
  const selIdx = commits.findIndex((c) => c.sha === selectedSha)
  return (
    <div className="border-tertiary bg-primary overflow-hidden rounded-md border">
      {commits.map((c, idx) => (
        <CommitRow
          active={c.sha === selectedSha}
          commit={c}
          held={selIdx >= 0 && idx < selIdx}
          idx={idx}
          key={c.sha}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

// fallow-ignore-next-line complexity
function CommitRow({ active, commit, held, idx, onSelect }: CommitRowProps) {
  const lines = commit.message.split('\n')
  const subject = lines[0] ?? ''
  const body = lines.slice(1).join('\n').trim()
  return (
    <div
      className={cn(
        'border-b border-tertiary last:border-b-0',
        held && 'opacity-50',
      )}
    >
      <button
        className={cn(
          'flex w-full min-w-0 items-center gap-3 px-3 py-2 text-left transition-colors',
          active ? 'bg-action/5' : 'hover:bg-secondary',
        )}
        onClick={() => onSelect(commit.sha)}
        type="button"
      >
        <span
          className={cn(
            'flex size-4 shrink-0 items-center justify-center rounded-full border',
            active ? 'border-action bg-action text-white' : 'border-secondary',
          )}
        >
          {active ? <Check size={10} strokeWidth={3} /> : null}
        </span>
        <span className="text-secondary shrink-0 font-mono text-xs">
          {commit.short_sha}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">{subject}</span>
        <CiStatusDot status={commit.ci_status} />
        <Badge variant="neutral">{idx === 0 ? 'tip' : `−${idx}`}</Badge>
      </button>
      {active && body ? (
        <pre className="bg-action/5 text-secondary overflow-x-auto px-3 pt-1 pb-3 pl-13 font-mono text-xs whitespace-pre-wrap">
          {body}
        </pre>
      ) : null}
      {active && commit.url ? (
        <div className="bg-action/5 px-3 pb-2 pl-13">
          <a
            className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
            href={commit.url}
            rel="noopener noreferrer"
            target="_blank"
          >
            <ExternalLink size={11} />
            View commit
          </a>
        </div>
      ) : null}
    </div>
  )
}
