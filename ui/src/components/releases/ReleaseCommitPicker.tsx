import { Check, ExternalLink, GitPullRequest } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import type { ChipColors } from '@/lib/chip-colors'
import { pullRequestRefs } from '@/lib/commit-refs'
import { cn } from '@/lib/utils'
import type { DeploymentCommitCiStatus } from '@/types'

import { CiStatusDot } from './CiStatusDot'

interface CommitRowProps {
  accent?: ChipColors | null
  active: boolean
  commit: PickerCommit
  displayNames: Map<string, string>
  held: boolean
  idx: number
  onSelect: (sha: string) => void
}

/**
 * Structural subset of a commit the picker needs — satisfied by both
 * `RecentCommit` (releases tab) and `DeploymentCommit` (deployments tab).
 */
interface PickerCommit {
  author?: null | string
  /** Only `RecentCommit` carries it; the promote flow resolves by name alone. */
  author_email?: null | string
  authored_at?: null | string
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
  const { displayNames } = useUserDisplayNames()
  const selIdx = commits.findIndex((c) => c.sha === selectedSha)
  return (
    <div className="border-tertiary bg-primary max-h-120 overflow-y-auto rounded-md border">
      {commits.map((c, idx) => (
        <CommitRow
          accent={accent}
          active={c.sha === selectedSha}
          commit={c}
          displayNames={displayNames}
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
  displayNames,
  held,
  idx,
  onSelect,
}: CommitRowProps) {
  const author = commit.author_email
    ? (displayNames.get(commit.author_email) ?? commit.author)
    : commit.author
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
        {/* Fixed-width columns, each rendered even when empty, so age /
            author / status line up down the list. */}
        <div className="grid shrink-0 grid-cols-[2.5rem_9rem_1.25rem] items-center gap-3">
          <span className="text-tertiary truncate text-right text-xs">
            {commit.authored_at ? (
              <RelativeTime value={commit.authored_at} variant="narrow" />
            ) : null}
          </span>
          <span className="min-w-0 truncate">
            {author ? (
              // The row itself is the select control, so the identity chip
              // can't link to a profile (no anchors inside a button).
              <UserIdentity
                actor={commit.author}
                displayName={author}
                email={commit.author_email}
                linkToProfile={false}
                size="small"
              />
            ) : null}
          </span>
          {/* ``unknown`` is the API's null-equivalent (e.g. compare results
              carry no check status) — skip the useless gray dot. */}
          <span className="flex justify-center">
            {commit.ci_status !== 'unknown' ? (
              <CiStatusDot status={commit.ci_status} />
            ) : null}
          </span>
        </div>
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
      {/* The row itself is the select control, so ``#N`` references can't be
          linked inline (no anchors inside a button) — they get their own
          affordance here, beside the commit link. */}
      {active && commit.url ? (
        <div
          className={cn(
            'flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-2 pl-13',
            !accent && 'bg-action/5',
          )}
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
          {pullRequestRefs(subject, commit.url).map((ref) => (
            <a
              className="text-warning inline-flex items-center gap-1 text-xs hover:underline"
              href={ref.href}
              key={ref.href}
              rel="noopener noreferrer"
              target="_blank"
            >
              <GitPullRequest size={11} />
              {ref.label}
            </a>
          ))}
        </div>
      ) : null}
    </div>
  )
}
