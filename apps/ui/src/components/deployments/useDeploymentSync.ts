// Sidebar "sync" action: refreshes everything the Deployments tab reads
// from imbi's own stores — the ClickHouse commit/tag history and the
// release/deployment state resynced from the remote's deployment
// records. Both arms are background jobs (enqueue + status poll).
import { useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import { useCommitSync } from '@/hooks/useCommitSync'
import { useProjectDeploymentResync } from '@/hooks/useDeploymentResync'
import type { UserResponse } from '@/types'

const DATA_KEYS = ['recentCommits', 'releaseHistory', 'currentReleases']

export function useDeploymentSync(orgSlug: string, projectId: string) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const commitSyncAllowed = canSyncCommits(user)
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

// Commit sync (POST /commits/sync) is independently permissioned. Gating this
// arm lets a user with deployment:write but not commits:write still get a
// clean release resync instead of a confusing 403 from the commit-sync call.
function canSyncCommits(user: null | UserResponse): boolean {
  if (!user) return false
  return (
    user.is_admin === true ||
    (user.permissions ?? []).includes('project:commits:write')
  )
}
