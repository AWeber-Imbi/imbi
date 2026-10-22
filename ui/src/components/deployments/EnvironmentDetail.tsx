import { Info } from 'lucide-react'

import type { ChipColors } from '@/lib/chip-colors'
import type { RecentCommit } from '@/types'

import { CommitDeployCard } from './CommitDeployCard'
import { CurrentlyRunningCard } from './CurrentlyRunningCard'
import { PendingPromoteCard } from './PendingPromoteCard'
import { PendingReleasesCard } from './PendingReleasesCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

interface EnvironmentDetailProps {
  accent: ChipColors | null
  actions: DeploymentActions
  canTrigger: boolean
  orgSlug: string
  projectId: string
  /** Synced default-branch commit history, newest first. */
  recentCommits: RecentCommit[]
  stage: PipelineStage
}

/**
 * Detail pane for the selected environment. The stage kind picks the
 * hero card: commit-based deploys for the entry env, an inline promote
 * form when the upstream runs untagged commits, or the pending-release
 * stack when the upstream already runs tags.
 *
 * A release already cut inside a promote range (a tag made out of band)
 * doesn't get its own card: the promote form drops it from the commits it
 * offers, so no second tag is cut over it, and the currently-running card's
 * recent-releases row is where it gets deployed. The pending-release stack
 * stands in only when there is nothing left to tag above it.
 */
export function EnvironmentDetail({
  accent,
  actions,
  canTrigger,
  orgSlug,
  projectId,
  recentCommits,
  stage,
}: EnvironmentDetailProps) {
  // The API refuses a deploy into an env with `can_deploy` false and a
  // promote into one without `can_promote`. Unset flags take the API
  // defaults: deployable, not promotable.
  const canDeploy = stage.env.can_deploy !== false
  const canPromote = stage.env.can_promote === true
  const envName = stage.env.name
  if (stage.kind === 'commit') {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {canDeploy ? null : <DisabledNotice action="deploy" env={envName} />}
        <CommitDeployCard
          accent={accent}
          actions={actions}
          canTrigger={canTrigger && canDeploy}
          orgSlug={orgSlug}
          projectId={projectId}
          recentCommits={recentCommits}
          stage={stage}
        />
      </div>
    )
  }
  // On a promote stage the form is the hero. It steps aside only when a
  // pending release accounts for every commit waiting, leaving nothing to
  // tag — then deploying that release is the whole move and the
  // pending-release stack says so.
  const showPromote =
    stage.kind === 'promote' &&
    (stage.pendingReleases.length === 0 || stage.promotableCommits.length > 0)
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {showPromote && !canPromote ? (
        <DisabledNotice action="promote" env={envName} />
      ) : null}
      {!showPromote && !canDeploy ? (
        <DisabledNotice action="deploy" env={envName} />
      ) : null}
      {showPromote ? (
        <PendingPromoteCard
          accent={accent}
          actions={actions}
          canTrigger={canTrigger && canPromote}
          orgSlug={orgSlug}
          projectId={projectId}
          stage={stage}
        />
      ) : (
        <PendingReleasesCard
          accent={accent}
          actions={actions}
          canTrigger={canTrigger && canDeploy}
          orgSlug={orgSlug}
          projectId={projectId}
          recentCommits={recentCommits}
          stage={stage}
        />
      )}
      <CurrentlyRunningCard
        accent={accent}
        actions={actions}
        canTrigger={canTrigger && canDeploy}
        orgSlug={orgSlug}
        projectId={projectId}
        stage={stage}
      />
    </div>
  )
}

function DisabledNotice({
  action,
  env,
}: {
  action: 'deploy' | 'promote'
  env: string
}) {
  return (
    <div className="border-tertiary text-secondary flex gap-2 rounded-md border px-3 py-2.5">
      <Info className="mt-0.5 size-3.5 shrink-0" />
      <span className="text-xs leading-relaxed">
        {action === 'deploy'
          ? `Direct deploys into ${env} are turned off. An admin can allow them on the environment.`
          : `Promotion into ${env} is turned off. An admin can allow it on the environment.`}
      </span>
    </div>
  )
}
