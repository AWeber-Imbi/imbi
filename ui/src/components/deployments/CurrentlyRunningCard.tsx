import { useState } from 'react'

import {
  Ban,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock,
  Globe,
  RotateCcw,
} from 'lucide-react'

import { BlockReleaseDialog } from '@/components/releases/BlockReleaseDialog'
import { CiStatusDot } from '@/components/releases/CiStatusDot'
import { useReleaseBlockMutation } from '@/components/releases/useReleaseBlockMutation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import type { ChipColors } from '@/lib/chip-colors'
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
  orgSlug: string
  projectId: string
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
  orgSlug,
  projectId,
  stage,
}: CurrentlyRunningCardProps) {
  const [openTag, setOpenTag] = useState<null | string>(null)
  const [confirming, setConfirming] = useState<null | ReleaseHistoryEntry>(null)
  const [blocking, setBlocking] = useState<null | string>(null)
  const {
    block,
    isPending: blockPending,
    unblock,
  } = useReleaseBlockMutation({
    orgSlug,
    projectId,
  })
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
                <RelativeTime
                  value={stage.current.last_event_at}
                  variant="long"
                />
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

        {stage.currentHistoryEntry ? (
          <section className="mb-4">
            <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
              Release notes ·{' '}
              <span className="font-mono normal-case">
                {stage.currentHistoryEntry.tag}
              </span>
            </p>
            <div className="border-tertiary rounded-md border px-3.5 py-3">
              <ReleaseNotesMarkdown
                notes={stage.currentHistoryEntry.notes_markdown}
              />
            </div>
          </section>
        ) : null}

        {stage.rollbackTargets.length > 0 ? (
          <div>
            <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
              Recent releases
            </p>
            {stage.rollbackTargets.map((rel) => (
              <RollbackRow
                blockPending={blockPending}
                canTrigger={canTrigger}
                isOpen={openTag === rel.tag}
                key={rel.tag}
                onBlock={() => setBlocking(rel.tag)}
                onRollback={() => setConfirming(rel)}
                onToggle={() =>
                  setOpenTag((o) => (o === rel.tag ? null : rel.tag))
                }
                onUnblock={() => unblock(rel.tag)}
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

      <BlockReleaseDialog
        isPending={blockPending}
        onBlock={(reason) => {
          if (blocking) block(blocking, reason)
          setBlocking(null)
        }}
        onOpenChange={(next) => {
          if (!next) setBlocking(null)
        }}
        open={blocking !== null}
        tag={blocking ?? ''}
      />
    </StageCardShell>
  )
}

// fallow-ignore-next-line complexity
function RollbackRow({
  blockPending,
  canTrigger,
  isOpen,
  onBlock,
  onRollback,
  onToggle,
  onUnblock,
  rel,
}: {
  blockPending: boolean
  canTrigger: boolean
  isOpen: boolean
  onBlock: () => void
  onRollback: () => void
  onToggle: () => void
  onUnblock: () => void
  rel: ReleaseHistoryEntry
}) {
  const blocked = !!rel.blocked
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
          <RelativeTime
            className="text-tertiary text-xs"
            tooltip={false}
            value={rel.published_at}
          />
        </button>
        {/* A blocked release can't be rolled back to, so the badge takes the
            button's place rather than sitting beside a dead control. */}
        {blocked ? (
          <Badge className="inline-flex items-center gap-1" variant="danger">
            <Ban className="size-3" />
            Blocked
          </Badge>
        ) : (
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
        )}
        {blocked ? (
          // Keep the glyph in the slot so rows stay aligned; red, and inert
          // because the Blocked badge already names the state and Unblock
          // lives with the reason in the expanded row.
          <span
            aria-hidden="true"
            className="text-danger flex h-7 items-center px-2"
          >
            <Ban className="size-3.5" />
          </span>
        ) : (
          <Button
            aria-label={`Block ${rel.tag}`}
            className="text-tertiary hover:text-danger h-7 px-2"
            disabled={blockPending}
            onClick={onBlock}
            size="sm"
            title={`Block ${rel.tag} from being deployed`}
            type="button"
            variant="ghost"
          >
            <Ban className="size-3.5" />
          </Button>
        )}
      </div>
      {isOpen ? (
        <div className="px-2 pb-3 pl-8">
          {blocked ? (
            <div className="text-danger mb-2 flex items-start gap-1.5 text-xs leading-relaxed">
              <Ban className="mt-0.5 size-3.5 shrink-0" />
              <span>
                Blocked from deploying and promoting
                {rel.blocked_reason ? <> — {rel.blocked_reason}</> : null}
                {rel.blocked_by ? <> · by {rel.blocked_by}</> : null}
              </span>
              <Button
                className="text-danger hover:bg-danger ml-auto h-auto shrink-0 px-2 py-0.5 text-xs"
                disabled={blockPending}
                onClick={onUnblock}
                type="button"
                variant="ghost"
              >
                Unblock
              </Button>
            </div>
          ) : null}
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
