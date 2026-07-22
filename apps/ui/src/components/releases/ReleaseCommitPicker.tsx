import { Check, ExternalLink } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { ChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'
import type { DeploymentCommitCiStatus } from '@/types'

import { CiStatusDot } from './CiStatusDot'

interface CommitRowProps {
  accent?: ChipColors | null
  active: boolean
  commit: PickerCommit
  held: boolean
  idx: number
  onSelect: (sha: string) => void
}

/**
 * Structural subset of a commit the picker needs — satisfied by both
 * `RecentCommit` (releases tab) and `DeploymentCommit` (deployments tab).
 */
interface PickerCommit {
  ci_status: DeploymentCommitCiStatus
  message: string
  sha: string
  short_sha: string
  url?: null | string
}

interface ReleaseCommitPickerProps {
  /**
   * Optional selection color (e.g. the target environment's derived
   * palette). Defaults to the amber action color.
   */
  accent?: ChipColors | null
  commits: PickerCommit[]
  onSelect: (sha: string) => void
  selectedSha: null | string
}

/**
 * Selectable commit list for the release form. Newest-first; commits newer
 * than the selection dim (they'd be held back). The selected row expands to
 * its full commit message.
 */
export function ReleaseCommitPicker({
  accent,
  commits,
  onSelect,
  selectedSha,
}: ReleaseCommitPickerProps) {
  const selIdx = commits.findIndex((c) => c.sha === selectedSha)
  return (
    <div className="border-tertiary bg-primary max-h-120 overflow-y-auto rounded-md border">
      {commits.map((c, idx) => (
        <CommitRow
          accent={accent}
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
function CommitRow({
  accent,
  active,
  commit,
  held,
  idx,
  onSelect,
}: CommitRowProps) {
  const lines = commit.message.split('\n')
  const subject = lines[0] ?? ''
  const body = lines.slice(1).join('\n').trim()
  const activeBg = active
    ? accent
      ? { backgroundColor: accent.bg }
      : undefined
    : undefined
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
          active ? !accent && 'bg-action/5' : 'hover:bg-secondary',
        )}
        onClick={() => onSelect(commit.sha)}
        style={activeBg}
        type="button"
      >
        <span
          className={cn(
            'flex size-4 shrink-0 items-center justify-center rounded-full border',
            active
              ? !accent && 'border-action bg-action text-white'
              : 'border-secondary',
          )}
          style={
            active && accent
              ? {
                  backgroundColor: accent.fg,
                  borderColor: accent.fg,
                  color: '#fff',
                }
              : undefined
          }
        >
          {active ? <Check size={10} strokeWidth={3} /> : null}
        </span>
        <span className="text-secondary shrink-0 font-mono text-xs">
          {commit.short_sha}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">{subject}</span>
        {/* ``unknown`` is the API's null-equivalent (e.g. compare results
            carry no check status) — skip the useless gray dot. */}
        {commit.ci_status !== 'unknown' ? (
          <CiStatusDot status={commit.ci_status} />
        ) : null}
        <Badge variant="neutral">{idx === 0 ? 'tip' : `−${idx}`}</Badge>
      </button>
      {active && body ? (
        <pre
          className={cn(
            'max-h-40 overflow-auto px-3 pt-1 pb-3 pl-13 font-mono text-xs whitespace-pre-wrap text-secondary',
            !accent && 'bg-action/5',
          )}
          style={activeBg}
        >
          {body}
        </pre>
      ) : null}
      {active && commit.url ? (
        <div
          className={cn('px-3 pb-2 pl-13', !accent && 'bg-action/5')}
          style={activeBg}
        >
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
