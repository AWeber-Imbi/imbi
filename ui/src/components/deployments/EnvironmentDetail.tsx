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
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {stage.kind === 'promote' ? (
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
        stage={stage}
      />
    </div>
  )
}
