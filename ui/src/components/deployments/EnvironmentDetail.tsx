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
  if (stage.kind === 'commit') {
    return (
      <CommitDeployCard
        accent={accent}
        actions={actions}
        canTrigger={canTrigger}
        recentCommits={recentCommits}
        stage={stage}
      />
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
      {showPromote ? (
        <PendingPromoteCard
          accent={accent}
          actions={actions}
          canTrigger={canTrigger}
          orgSlug={orgSlug}
          projectId={projectId}
          stage={stage}
        />
      ) : (
        <PendingReleasesCard
          accent={accent}
          actions={actions}
          canTrigger={canTrigger}
          recentCommits={recentCommits}
          stage={stage}
        />
      )}
      <CurrentlyRunningCard
        accent={accent}
        actions={actions}
        canTrigger={canTrigger}
        orgSlug={orgSlug}
        projectId={projectId}
        stage={stage}
      />
    </div>
  )
}
