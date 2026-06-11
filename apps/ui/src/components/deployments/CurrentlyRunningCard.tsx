import { useState } from 'react'

import { formatDistanceToNow } from 'date-fns'
import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock,
  Globe,
  RotateCcw,
} from 'lucide-react'

import { CiStatusDot } from '@/components/releases/CiStatusDot'
import { Button } from '@/components/ui/button'
import { UserIdentity } from '@/components/ui/user-identity'
import type { ChipColors } from '@/lib/chip-colors'
import { formatRelativeDate } from '@/lib/formatDate'
import { cn, sanitizeHttpUrl } from '@/lib/utils'
import type { ReleaseHistoryEntry } from '@/types'

import { ConfirmActionDialog } from './ConfirmActionDialog'
import type { PipelineStage } from './pipeline'
import { ReleaseNotesMarkdown } from './ReleaseNotesMarkdown'
import { StageCardShell } from './StageCardShell'
import type { DeploymentActions } from './useDeploymentActions'

interface CurrentlyRunningCardProps {
  accent: ChipColors | null
  actions: DeploymentActions
  canTrigger: boolean
  stage: PipelineStage
}

/**
 * What the environment runs now, plus the recent releases it can roll
 * back to (each expandable into its release notes).
 */
// fallow-ignore-next-line complexity
export function CurrentlyRunningCard({
  accent,
  actions,
  canTrigger,
  stage,
}: CurrentlyRunningCardProps) {
  const [openTag, setOpenTag] = useState<null | string>(null)
  const [confirming, setConfirming] = useState<null | ReleaseHistoryEntry>(null)
  const release = stage.current?.release ?? null
  const envUrl = sanitizeHttpUrl(stage.env.url ?? null)

  return (
    <StageCardShell
      accent={accent}
      aside={
        envUrl ? (
          <a
            className="inline-flex items-center gap-1.5 text-xs hover:underline"
            href={envUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            <Globe size={12} />
            {envUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')}
          </a>
        ) : undefined
      }
      icon={CircleDot}
      subtitle={
        release ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {stage.current?.last_event_at ? (
              <span className="inline-flex items-center gap-1.5">
                <Clock size={13} />
                Deployed{' '}
                {formatDistanceToNow(new Date(stage.current.last_event_at), {
                  addSuffix: true,
                })}
              </span>
            ) : null}
            {stage.current?.performed_by ? (
              <>
                <span aria-hidden="true">·</span>
                <UserIdentity
                  actor={stage.current.performed_by}
                  email={stage.current.performed_by_email}
                  size="small"
                />
              </>
            ) : null}
          </span>
        ) : undefined
      }
      title={
        <span className="flex items-baseline gap-2.5">
          Currently running
          {release ? (
            <>
              <span className="font-mono text-base">
                {release.tag ?? release.committish.slice(0, 7)}
              </span>
              {release.tag ? (
                <span className="text-tertiary font-mono text-xs font-normal">
                  {release.committish.slice(0, 7)}
                </span>
              ) : null}
              {stage.current?.ci_status &&
              stage.current.ci_status !== 'unknown' ? (
                <CiStatusDot status={stage.current.ci_status} />
              ) : null}
            </>
          ) : null}
        </span>
      }
    >
      <div className="px-4 py-4">
        {release ? null : (
          <p className="text-tertiary text-sm italic">Nothing deployed yet.</p>
        )}

        {stage.rollbackTargets.length > 0 ? (
          <div>
            <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
              Recent releases
            </p>
            {stage.rollbackTargets.map((rel) => (
              <RollbackRow
                canTrigger={canTrigger}
                isOpen={openTag === rel.tag}
                key={rel.tag}
                onRollback={() => setConfirming(rel)}
                onToggle={() =>
                  setOpenTag((o) => (o === rel.tag ? null : rel.tag))
                }
                rel={rel}
              />
            ))}
          </div>
        ) : null}
      </div>

      <ConfirmActionDialog
        confirmLabel={
          confirming ? `Roll back to ${confirming.tag}` : 'Roll back'
        }
        description={
          confirming ? (
            <>
              Redeploys <span className="font-mono">{confirming.tag}</span> to{' '}
              {stage.env.name}. {stage.env.name} will show as behind until you
              move forward again; no new tag is cut.
            </>
          ) : (
            ''
          )
        }
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (!confirming) return
          actions.deploy({
            action: 'deploy',
            envName: stage.env.name,
            envSlug: stage.env.slug,
            refLabel: confirming.tag,
            rollback: true,
            sha: confirming.sha,
          })
          setConfirming(null)
        }}
        open={confirming !== null}
        title={`Roll back ${stage.env.name}?`}
      />
    </StageCardShell>
  )
}

function RollbackRow({
  canTrigger,
  isOpen,
  onRollback,
  onToggle,
  rel,
}: {
  canTrigger: boolean
  isOpen: boolean
  onRollback: () => void
  onToggle: () => void
  rel: ReleaseHistoryEntry
}) {
  return (
    <div
      className={cn(
        '-mx-2 rounded-md transition-colors',
        isOpen && 'bg-secondary',
      )}
    >
      <div className="hover:bg-secondary flex items-center gap-3 rounded-md px-2 py-1">
        <button
          className="grid flex-1 cursor-pointer grid-cols-[0.8rem_8rem_1rem_4.5rem_1fr] items-center gap-3 text-left"
          onClick={onToggle}
          type="button"
        >
          {isOpen ? (
            <ChevronDown className="text-tertiary size-3.5" />
          ) : (
            <ChevronRight className="text-tertiary size-3.5" />
          )}
          <span className="font-mono text-sm font-semibold">{rel.tag}</span>
          <CiStatusDot size={13} status={rel.ci_status} />
          <span className="text-tertiary font-mono text-xs">
            {rel.short_sha}
          </span>
          <span className="text-tertiary text-xs">
            {formatRelativeDate(rel.published_at)}
          </span>
        </button>
        <Button
          className="h-7 px-2.5 text-xs"
          disabled={!canTrigger}
          onClick={onRollback}
          size="sm"
          type="button"
          variant="outline"
        >
          <RotateCcw className="mr-1 size-3.5" />
          Roll back
        </Button>
      </div>
      {isOpen ? (
        <div className="px-2 pb-3 pl-8">
          <ReleaseNotesMarkdown notes={rel.notes_markdown} />
          {rel.author ? (
            <div className="text-tertiary mt-2 inline-flex items-center gap-1.5 text-xs">
              released by
              <UserIdentity
                actor={rel.author}
                email={rel.author_email}
                size="small"
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
