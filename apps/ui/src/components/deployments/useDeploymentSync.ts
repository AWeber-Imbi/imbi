// Sidebar "sync" action: refreshes everything the Deployments tab reads
// from imbi's own stores — the ClickHouse commit/tag history (background
// job + poll, via useCommitSync) and the release/deployment state
// resynced from the remote's deployment records.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { resyncProjectDeployments } from '@/api/endpoints'
import { useCommitSync } from '@/hooks/useCommitSync'
import { extractApiErrorDetail } from '@/lib/apiError'

const DATA_KEYS = ['recentCommits', 'releaseHistory', 'currentReleases']

export function useDeploymentSync(orgSlug: string, projectId: string) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    for (const key of DATA_KEYS) {
      void queryClient.invalidateQueries({
        queryKey: [key, orgSlug, projectId],
      })
    }
  }

  const commitSync = useCommitSync(orgSlug, projectId, true, invalidate)
  const resyncMutation = useMutation({
    mutationFn: () => resyncProjectDeployments(orgSlug, projectId),
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
      commitSync.sync()
      resyncMutation.mutate()
    },
  }
}
