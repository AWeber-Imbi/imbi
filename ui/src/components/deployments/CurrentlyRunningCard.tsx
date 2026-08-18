import { type ReactNode, useEffect, useState } from 'react'

import {
  Ban,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock,
  Globe,
  Rocket,
  RotateCcw,
} from 'lucide-react'

import {
  CiFailureNotice,
  ciNeedsAcknowledgement,
  useCommitCheckStatus,
} from '@/components/deploy/CiFailureNotice'
import { BlockReleaseDialog } from '@/components/releases/BlockReleaseDialog'
import { CiStatusDot } from '@/components/releases/CiStatusDot'
import { useReleaseBlockMutation } from '@/components/releases/useReleaseBlockMutation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import type { ChipColors } from '@/lib/chip-colors'
import { cn, sanitizeHttpUrl } from '@/lib/utils'

import { ConfirmActionDialog } from './ConfirmActionDialog'
import type { PipelineStage, RecentRelease } from './pipeline'
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
 * What the environment runs now, plus the recent releases either side of
 * it (each expandable into its release notes). Releases below the running
 * one offer a roll back; releases above it — which is where a rolled-back
 * env sits — offer a forward deploy once validated upstream, and otherwise
 * list without a control, so this can't be used to jump the release train.
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
  const [confirming, setConfirming] = useState<null | RecentRelease>(null)
  const [blocking, setBlocking] = useState<null | string>(null)
  // Live CI status for the release in the confirm dialog. The row dots
  // come from the synced history and can lag; this is the state the API's
  // deploy gate will actually see.
  const { ciPending, ciStatus } = useCommitCheckStatus(
    orgSlug,
    projectId,
    confirming?.entry.sha ?? null,
  )
  const ciFailed = ciNeedsAcknowledgement(ciStatus)
  const [ciAcknowledged, setCiAcknowledged] = useState(false)
  useEffect(() => {
    setCiAcknowledged(false)
  }, [confirming?.entry.sha])
  const {
    block,
    isPending: blockPending,
    unblock,
  } = useReleaseBlockMutation({
    orgSlug,
    projectId,
  })
  const release = stage.current?.release ?? null
  // The tag the env is running. Prefer the history entry: when the deploy was
  // recorded against an untagged release, the entry is the one resolved by
  // committish, and it knows the tag that commit actually shipped under.
  const runningTag = stage.currentHistoryEntry?.tag ?? release?.tag ?? null
  const envUrl = sanitizeHttpUrl(stage.env.url ?? null)
  const upstreamName = stage.upstream?.name ?? 'upstream'
  // Why a release above the running one isn't offered — only sayable when
  // the upstream runs a tag to compare against. On a promote stage it runs
  // an untagged commit, so there is no claim to make and the row simply
  // carries no control.
  const unreachedLabel = stage.upstreamCurrent?.release?.tag
    ? `Not in ${upstreamName.toLowerCase()}`
    : null
  const confirm = confirmCopy(confirming, stage, upstreamName)

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
                {runningTag ?? release.committish.slice(0, 7)}
              </span>
              {runningTag ? (
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
            <ReleaseNotesMarkdown
              notes={stage.currentHistoryEntry.notes_markdown}
            />
          </section>
        ) : null}

        {stage.recentReleases.length > 0 ? (
          <div>
            <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
              Recent releases
            </p>
            {stage.recentReleases.map((row) => (
              <ReleaseRow
                blockPending={blockPending}
                canTrigger={canTrigger}
                isOpen={openTag === row.entry.tag}
                key={row.entry.tag}
                onBlock={() => setBlocking(row.entry.tag)}
                onDeploy={() => setConfirming(row)}
                onToggle={() =>
                  setOpenTag((o) =>
                    o === row.entry.tag ? null : row.entry.tag,
                  )
                }
                onUnblock={() => unblock(row.entry.tag)}
                row={row}
                unreachedLabel={unreachedLabel}
              />
            ))}
          </div>
        ) : null}
      </div>

      <ConfirmActionDialog
        // Held until CI has answered: an unresolved status cannot be told
        // apart from a green one, and dispatching on it skips the
        // acknowledgement the server would then demand with a 409.
        confirmDisabled={ciPending || (ciFailed && !ciAcknowledged)}
        confirmLabel={confirm.confirmLabel}
        description={confirm.description}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (!confirming) return
          actions.deploy({
            acknowledgeCiFailure: ciFailed && ciAcknowledged,
            action: 'deploy',
            envName: stage.env.name,
            envSlug: stage.env.slug,
            refLabel: confirming.entry.tag,
            rollback: confirming.relation === 'behind',
            sha: confirming.entry.sha,
          })
          setConfirming(null)
        }}
        open={confirming !== null}
        title={confirm.title}
      >
        <CiFailureNotice
          acknowledged={ciAcknowledged}
          action={confirming?.relation === 'behind' ? 'redeploy' : 'deploy'}
          ciStatus={ciStatus}
          onAcknowledgedChange={setCiAcknowledged}
          sha={confirming?.entry.sha ?? null}
        />
      </ConfirmActionDialog>

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

/**
 * Title, button label, and body for the confirm dialog, which serves both
 * directions. Falls back to roll-back wording while ``row`` is null — the
 * dialog stays mounted when closed so it can animate out, and no user sees
 * the fallback copy.
 */
function confirmCopy(
  row: null | RecentRelease,
  stage: PipelineStage,
  upstreamName: string,
): { confirmLabel: string; description: ReactNode; title: string } {
  const env = stage.env.name
  if (row?.relation === 'ahead') {
    return {
      confirmLabel: `Deploy ${row.entry.tag} to ${env.toLowerCase()}`,
      description: (
        <>
          Deploys <span className="font-mono">{row.entry.tag}</span> to {env} —
          the release {env.toLowerCase()} was on before it was rolled back, or a
          newer one already validated in {upstreamName.toLowerCase()}. No new
          tag is cut.
        </>
      ),
      title: `Deploy to ${env}?`,
    }
  }
  return {
    confirmLabel: row ? `Roll back to ${row.entry.tag}` : 'Roll back',
    description: row ? (
      <>
        Redeploys <span className="font-mono">{row.entry.tag}</span> to {env}.{' '}
        {env} will show as behind until you move forward again; no new tag is
        cut.
      </>
    ) : (
      ''
    ),
    title: `Roll back ${env}?`,
  }
}

// fallow-ignore-next-line complexity
function ReleaseRow({
  blockPending,
  canTrigger,
  isOpen,
  onBlock,
  onDeploy,
  onToggle,
  onUnblock,
  row,
  unreachedLabel,
}: {
  blockPending: boolean
  canTrigger: boolean
  isOpen: boolean
  onBlock: () => void
  onDeploy: () => void
  onToggle: () => void
  onUnblock: () => void
  row: RecentRelease
  unreachedLabel: null | string
}) {
  const rel = row.entry
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
        <RowAction
          blocked={blocked}
          canTrigger={canTrigger}
          onDeploy={onDeploy}
          row={row}
          unreachedLabel={unreachedLabel}
        />
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

/**
 * The row's action slot. Badges take the button's place rather than
 * sitting beside a dead control:
 *
 *   current   — "Running"; there is nothing to move to.
 *   blocked   — "Blocked"; can't be deployed or promoted at all.
 *   unreached — no control; shipping it here would jump the release train.
 *               Says why via ``unreachedLabel`` when the upstream runs a
 *               tag to compare against.
 *   ahead     — deploy; it is validated upstream.
 *   behind    — roll back; this env already ran it.
 */
function RowAction({
  blocked,
  canTrigger,
  onDeploy,
  row,
  unreachedLabel,
}: {
  blocked: boolean
  canTrigger: boolean
  onDeploy: () => void
  row: RecentRelease
  unreachedLabel: null | string
}) {
  if (row.relation === 'current') {
    return (
      <Badge className="inline-flex items-center gap-1" variant="success">
        <CircleDot className="size-3" />
        Running
      </Badge>
    )
  }
  if (blocked) {
    return (
      <Badge className="inline-flex items-center gap-1" variant="danger">
        <Ban className="size-3" />
        Blocked
      </Badge>
    )
  }
  if (row.relation === 'unreached') {
    if (!unreachedLabel) return null
    return (
      <Badge className="inline-flex items-center gap-1" variant="neutral">
        {unreachedLabel}
      </Badge>
    )
  }
  const ahead = row.relation === 'ahead'
  const Icon = ahead ? Rocket : RotateCcw
  const verb = ahead ? 'Deploy' : 'Roll back'
  return (
    <Button
      aria-label={`${verb} ${row.entry.tag}`}
      className="h-7 px-2.5 text-xs"
      disabled={!canTrigger}
      onClick={onDeploy}
      size="sm"
      type="button"
      variant="outline"
    >
      <Icon className="mr-1 size-3.5" />
      {verb}
    </Button>
  )
}
