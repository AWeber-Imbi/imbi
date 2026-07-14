// Sidebar "sync" action: refreshes everything the Deployments tab reads
// from imbi's own stores — the ClickHouse commit/tag history (background
// job + poll, via useCommitSync) and the release/deployment state
// resynced from the remote's deployment records.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { resyncProjectDeployments } from '@/api/endpoints'
import { useAuth } from '@/hooks/useAuth'
import { useCommitSync } from '@/hooks/useCommitSync'
import { extractApiErrorDetail } from '@/lib/apiError'
import { DEEP_RESYNC_LIMIT } from '@/lib/resync'
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
  const resyncMutation = useMutation({
    mutationFn: () =>
      resyncProjectDeployments(orgSlug, projectId, {
        limit: DEEP_RESYNC_LIMIT,
      }),
    onError: (err) =>
      toast.error(extractApiErrorDetail(err) ?? 'Failed to resync releases'),
    onSuccess: (summary) => {
      invalidate()
      const releases = summary.releases_created + summary.releases_updated
      toast.success(
        `Releases resynced — ${releases} release(s) and ` +
          `${summary.events_recorded} event(s) updated`,
      )
      if (summary.errors.length > 0) {
        toast.warning(
          `Release resync finished with ${summary.errors.length} error(s)`,
          { description: summary.errors[0]?.detail },
        )
      }
    },
  })

  return {
    isSyncing: commitSync.isSyncing || resyncMutation.isPending,
    sync: () => {
      if (commitSyncAllowed) commitSync.sync()
      resyncMutation.mutate()
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
