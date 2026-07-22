import { Fragment, useState } from 'react'

import {
  ExternalLink,
  GitCommitHorizontal,
  Loader2,
  RotateCcw,
  Upload,
} from 'lucide-react'

import { CiStatusDot } from '@/components/releases/CiStatusDot'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { UserIdentity } from '@/components/ui/user-identity'
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
  recentCommits,
  stage,
}: CommitDeployCardProps) {
  const [confirming, setConfirming] = useState<null | {
    commit: RecentCommit
    rollback: boolean
  }>(null)

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
          <>
            On <span className="font-mono">{currentSha.slice(0, 7)}</span> ·
            deploy a newer commit or roll back
          </>
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
      />
    </StageCardShell>
  )
}

// fallow-ignore-next-line complexity
function CommitRow({
  accent,
  actionPending,
  canTrigger,
  commit,
  isCurrent,
  isHead,
  onAction,
  rollback,
}: {
  accent: ChipColors | null
  actionPending: boolean
  canTrigger: boolean
  commit: RecentCommit
  isCurrent: boolean
  isHead: boolean
  onAction: (rollback: boolean) => void
  rollback: boolean
}) {
  return (
    <li
      className="border-tertiary flex min-w-0 items-center gap-3 border-b px-3 py-1.5 last:border-b-0"
      style={isCurrent && accent ? { backgroundColor: accent.bg } : undefined}
    >
      <span className="shrink-0 font-mono text-xs">{commit.short_sha}</span>
      {isHead ? <Badge variant="outline">HEAD</Badge> : null}
      <span className="min-w-0 flex-1 truncate text-sm">
        {commit.message.split('\n')[0]}
      </span>
      {commit.ci_status !== 'unknown' ? (
        <CiStatusDot status={commit.ci_status} />
      ) : null}
      {commit.author ? (
        <span className="hidden shrink-0 sm:inline">
          <UserIdentity
            actor={commit.author}
            displayName={commit.author}
            email={commit.author_email}
            size="small"
          />
        </span>
      ) : null}
      {commit.url ? (
        <a
          aria-label="View commit"
          className="text-tertiary hover:text-primary"
          href={commit.url}
          rel="noopener noreferrer"
          target="_blank"
        >
          <ExternalLink className="size-3.5" />
        </a>
      ) : null}
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
    </li>
  )
}
