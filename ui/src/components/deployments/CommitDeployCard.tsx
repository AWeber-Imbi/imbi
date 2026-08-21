import { Fragment, useEffect, useState } from 'react'

import {
  Clock,
  ExternalLink,
  GitCommitHorizontal,
  Loader2,
  RotateCcw,
  Upload,
} from 'lucide-react'

import {
  CiFailureNotice,
  ciNeedsAcknowledgement,
  useCommitCheckStatus,
} from '@/components/deploy/CiFailureNotice'
import { CiStatusDot } from '@/components/releases/CiStatusDot'
import { DriftIndicator } from '@/components/releases/DriftIndicator'
import { TagBadge } from '@/components/releases/TagBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CommitSubject } from '@/components/ui/commit-subject'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import type { ChipColors } from '@/lib/chip-colors'
import type { RecentCommit } from '@/types'

import { ConfirmActionDialog } from './ConfirmActionDialog'
import type { PipelineStage } from './pipeline'
import { shaMatch } from './pipeline'
import { StageCardShell } from './StageCardShell'
import type { DeploymentActions } from './useDeploymentActions'

interface CommitDeployCardProps {
  accent: ChipColors | null
  actions: DeploymentActions
  canTrigger: boolean
  orgSlug: string
  projectId: string
  /** Synced default-branch commit history, newest first. */
  recentCommits: RecentCommit[]
  stage: PipelineStage
}

const DISPLAY_LIMIT = 25

/**
 * The entry environment: tracks raw commits off the default branch
 * (from imbi's synced history). Deploy a newer commit forward, or roll
 * back to an older one — no promotion happens here.
 */
// fallow-ignore-next-line complexity
export function CommitDeployCard({
  accent,
  actions,
  canTrigger,
  orgSlug,
  projectId,
  recentCommits,
  stage,
}: CommitDeployCardProps) {
  const [confirming, setConfirming] = useState<null | {
    commit: RecentCommit
    rollback: boolean
  }>(null)
  // Git author names vary per commit (a squash-merge records the source
  // host's display name, a local commit whatever git config holds), so rows
  // resolve through the Imbi user by email and only fall back to the raw
  // name — otherwise the same person renders under two names and two
  // avatar tints in one list.
  const { displayNames } = useUserDisplayNames()

  // Live CI status for the commit in the confirm dialog. The row dots come
  // from imbi's synced history and can lag; this is the state the API's
  // deploy gate will actually see, so the two cannot disagree.
  const { ciPending, ciStatus } = useCommitCheckStatus(
    orgSlug,
    projectId,
    confirming?.commit.sha ?? null,
  )
  const ciFailed = ciNeedsAcknowledgement(ciStatus)
  const [ciAcknowledged, setCiAcknowledged] = useState(false)
  useEffect(() => {
    setCiAcknowledged(false)
  }, [confirming?.commit.sha])

  const currentSha = stage.current?.release?.committish ?? null
  const matchesCurrent = (c: RecentCommit) =>
    !!currentSha && shaMatch(c.sha, currentSha)

  // Show the most recent window; when the deployed commit is older than
  // it, pull it forward from the rest of the synced history (or pin a
  // bare-SHA row) so the list always anchors on what's running.
  const windowRows = recentCommits.slice(0, DISPLAY_LIMIT)
  const currentInWindow = windowRows.some(matchesCurrent)
  const pinnedCurrent =
    !currentInWindow && currentSha && windowRows.length > 0
      ? (recentCommits.find(matchesCurrent) ?? {
          authored_at: '',
          ci_status: 'unknown' as const,
          message: 'Not in the synced commit history — try a sync',
          sha: currentSha,
          short_sha: currentSha.slice(0, 7),
        })
      : null
  const rows = pinnedCurrent ? [...windowRows, pinnedCurrent] : windowRows
  const deployedIdx = rows.findIndex(matchesCurrent)

  return (
    <StageCardShell
      accent={accent}
      icon={GitCommitHorizontal}
      subtitle={
        currentSha ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              On <span className="font-mono">{currentSha.slice(0, 7)}</span>
            </span>
            {stage.current?.last_event_at ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="inline-flex items-center gap-1.5">
                  <Clock size={13} />
                  Deployed{' '}
                  <RelativeTime
                    value={stage.current.last_event_at}
                    variant="long"
                  />
                </span>
              </>
            ) : null}
            {stage.current?.performed_by ? (
              <>
                <span>by</span>
                <UserIdentity
                  actor={stage.current.performed_by}
                  email={stage.current.performed_by_email}
                  size="small"
                />
              </>
            ) : null}
            <span aria-hidden="true">·</span>
            <span>deploy a newer commit or roll back</span>
          </span>
        ) : (
          'Nothing deployed yet — deploy a commit to get started'
        )
      }
      title={stage.env.name}
    >
      <div className="px-4 py-4">
        <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
          Recent commits
        </p>
        {rows.length === 0 ? (
          <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
            No synced commits yet — run a sync from the pipeline sidebar.
          </p>
        ) : (
          <ul className="border-tertiary max-h-120 overflow-y-auto rounded-md border">
            {rows.map((c, idx) => (
              <Fragment key={c.sha}>
                {pinnedCurrent && idx === rows.length - 1 ? (
                  <li className="border-tertiary text-tertiary border-b px-3 py-1 text-center text-xs italic last:border-b-0">
                    … older commits not shown
                  </li>
                ) : null}
                <CommitRow
                  accent={accent}
                  actionPending={actions.deployPendingSha === c.sha}
                  canTrigger={canTrigger && !actions.deployPending}
                  commit={c}
                  displayNames={displayNames}
                  isCurrent={idx === deployedIdx}
                  isHead={idx === 0}
                  onAction={(rollback) =>
                    setConfirming({ commit: c, rollback })
                  }
                  rollback={deployedIdx >= 0 && idx > deployedIdx}
                />
              </Fragment>
            ))}
          </ul>
        )}
      </div>

      <ConfirmActionDialog
        // Held until CI has answered: an unresolved status cannot be told
        // apart from a green one, and dispatching on it skips the
        // acknowledgement the server would then demand with a 409.
        confirmDisabled={ciPending || (ciFailed && !ciAcknowledged)}
        confirmLabel={
          confirming
            ? `${confirming.rollback ? 'Roll back to' : 'Deploy'} ${confirming.commit.short_sha}`
            : 'Deploy'
        }
        description={
          confirming ? (
            <>
              {confirming.rollback ? 'Redeploys' : 'Deploys'}{' '}
              <span className="font-mono">{confirming.commit.short_sha}</span> (
              {confirming.commit.message.split('\n')[0]}) to {stage.env.name}.
            </>
          ) : (
            ''
          )
        }
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (!confirming) return
          actions.deploy({
            acknowledgeCiFailure: ciFailed && ciAcknowledged,
            action: 'deploy',
            envName: stage.env.name,
            envSlug: stage.env.slug,
            refLabel: null,
            rollback: confirming.rollback,
            sha: confirming.commit.sha,
          })
          setConfirming(null)
        }}
        open={confirming !== null}
        title={
          confirming?.rollback
            ? `Roll back ${stage.env.name}?`
            : `Deploy to ${stage.env.name}?`
        }
      >
        <CiFailureNotice
          acknowledged={ciAcknowledged}
          action={confirming?.rollback ? 'redeploy' : 'deploy'}
          ciStatus={ciStatus}
          onAcknowledgedChange={setCiAcknowledged}
          sha={confirming?.commit.sha ?? null}
        />
      </ConfirmActionDialog>
    </StageCardShell>
  )
}

// fallow-ignore-next-line complexity
function CommitRow({
  accent,
  actionPending,
  canTrigger,
  commit,
  displayNames,
  isCurrent,
  isHead,
  onAction,
  rollback,
}: {
  accent: ChipColors | null
  actionPending: boolean
  canTrigger: boolean
  commit: RecentCommit
  displayNames: Map<string, string>
  isCurrent: boolean
  isHead: boolean
  onAction: (rollback: boolean) => void
  rollback: boolean
}) {
  const author = commit.author_email
    ? (displayNames.get(commit.author_email) ?? commit.author)
    : commit.author
  return (
    <li
      className="border-tertiary flex min-w-0 items-center gap-3 border-b px-3 py-1.5 last:border-b-0"
      style={isCurrent && accent ? { backgroundColor: accent.bg } : undefined}
    >
      <span className="flex w-5 shrink-0 justify-center">
        <DriftIndicator drift={commit.drift_detected} />
      </span>
      <span className="shrink-0 font-mono text-xs">{commit.short_sha}</span>
      {isHead ? <Badge variant="outline">HEAD</Badge> : null}
      <TagBadge tag={commit.tag} />
      <CommitSubject
        className="min-w-0 flex-1 truncate text-sm"
        commitUrl={commit.url}
        message={commit.message}
      />
      {/* Fixed-width columns, each rendered even when empty, so status /
          age / author / link / action line up down the list — including the
          HEAD row, whose action is a badge rather than a button. */}
      <div className="grid shrink-0 grid-cols-[1.25rem_2.5rem_9rem_6.5rem_6.5rem] items-center gap-3">
        <span className="flex justify-center">
          {commit.ci_status !== 'unknown' ? (
            <CiStatusDot status={commit.ci_status} />
          ) : null}
        </span>
        <span className="text-tertiary truncate text-right text-xs">
          {commit.authored_at ? (
            <RelativeTime value={commit.authored_at} variant="narrow" />
          ) : null}
        </span>
        <span className="min-w-0 truncate">
          {author ? (
            <UserIdentity
              actor={commit.author}
              displayName={author}
              email={commit.author_email}
              size="small"
            />
          ) : null}
        </span>
        <span className="min-w-0">
          {commit.url ? (
            <a
              className="text-tertiary hover:text-primary inline-flex min-w-0 items-center gap-1 text-xs"
              href={commit.url}
              rel="noopener noreferrer"
              target="_blank"
            >
              <ExternalLink className="size-3.5 shrink-0" />
              <span className="truncate">View commit</span>
            </a>
          ) : null}
        </span>
        <span className="flex justify-end">
          {isCurrent ? (
            <Badge variant="neutral">deployed</Badge>
          ) : (
            <Button
              disabled={!canTrigger}
              onClick={() => onAction(rollback)}
              size="sm"
              type="button"
              variant="ghost"
            >
              {actionPending ? (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              ) : rollback ? (
                <RotateCcw className="mr-1 size-3.5" />
              ) : (
                <Upload className="mr-1 size-3.5" />
              )}
              {rollback ? 'Roll back' : 'Deploy'}
            </Button>
          )}
        </span>
      </div>
    </li>
  )
}
