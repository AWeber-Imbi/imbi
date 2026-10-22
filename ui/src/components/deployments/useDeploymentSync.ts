// The "sync" action behind the Deployments sidebar and the Releases tab
// header: refreshes everything those tabs read from imbi's own stores —
// the ClickHouse commit/tag history and the release/deployment state
// resynced from the remote's deployment records. Both arms are background
// jobs (enqueue + status poll).
import { useQueryClient } from '@tanstack/react-query'

import { useCommitSync } from '@/hooks/useCommitSync'
import { useProjectDeploymentResync } from '@/hooks/useDeploymentResync'
import { useHasPermission } from '@/hooks/useHasPermission'

const DATA_KEYS = [
  'recentCommits',
  'releaseHistory',
  'currentReleases',
  // The Releases tab syncs through this hook too, and its drift card is
  // exactly what a sync is expected to move.
  'releaseDrift',
]

export function useDeploymentSync(orgSlug: string, projectId: string) {
  const queryClient = useQueryClient()
  // Commit sync (POST /commits/sync) is independently permissioned. Gating
  // this arm lets a user with deployment:write but not commits:write still
  // get a clean release resync instead of a confusing 403 from the
  // commit-sync call.
  const commitSyncAllowed = useHasPermission('project:commits:write', orgSlug)
  const invalidate = () => {
    for (const key of DATA_KEYS) {
      void queryClient.invalidateQueries({
        queryKey: [key, orgSlug, projectId],
      })
    }
  }

  const commitSync = useCommitSync(
    orgSlug,
    projectId,
    commitSyncAllowed,
    invalidate,
  )
  const resync = useProjectDeploymentResync(orgSlug, projectId, invalidate)

  return {
    isSyncing: commitSync.isSyncing || resync.isSyncing,
    sync: () => {
      if (commitSyncAllowed) commitSync.sync()
      resync.sync()
    },
  }
}
