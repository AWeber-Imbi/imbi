import { useEffect, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { CommitSyncState, CommitSyncStatus } from '@/api/endpoints'
import {
  getProjectCommitSyncStatus,
  syncProjectCommitsAndTags,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

const POLL_MS = 3000

// Drives the Project Doctor "Sync Commits & Tags" button: enqueues the
// background job and polls the project's sync-status while a run is in
// flight, toasting the terminal result so the user gets feedback even
// though the work happens off-request.
export function useCommitSync(
  orgSlug: string,
  projectId: string,
  enabled: boolean,
  /** Invoked when a run completes successfully (e.g. to refresh data). */
  onComplete?: () => void,
) {
  const queryClient = useQueryClient()
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  const statusQuery = useQuery({
    enabled: enabled && !!orgSlug && !!projectId,
    queryFn: ({ signal }): Promise<CommitSyncStatus> =>
      getProjectCommitSyncStatus(orgSlug, projectId, signal),
    queryKey: ['commitSyncStatus', orgSlug, projectId],
    // Poll only while a run is queued/running; settle back to idle.
    refetchInterval: (query) =>
      isActive(query.state.data?.status) ? POLL_MS : false,
  })

  // Toast the terminal result when a poll observes the run leaving the
  // active state. The ref guards against toasting stale state on mount.
  const previous = useRef<CommitSyncState | undefined>(undefined)
  useEffect(() => {
    const data = statusQuery.data
    if (!data) return
    if (!isActive(data.status) && data.status !== previous.current) {
      announceTerminal(data)
      if (data.status === 'success') onCompleteRef.current?.()
    }
    previous.current = data.status
  }, [statusQuery.data])

  const mutation = useMutation({
    mutationFn: () => syncProjectCommitsAndTags(orgSlug, projectId),
    onError: (err) =>
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to start commit & tag sync',
      ),
    onSuccess: (res) => {
      if (res.enqueued) {
        toast.success('Commit & tag sync started')
        void queryClient.invalidateQueries({
          queryKey: ['commitSyncStatus', orgSlug, projectId],
        })
      } else {
        toast.info('A commit & tag sync is already in progress')
      }
    },
  })

  const isSyncing = mutation.isPending || isActive(statusQuery.data?.status)
  return { isSyncing, sync: mutation.mutate }
}

// Announce a run's terminal outcome once it leaves the active state.
function announceTerminal(data: CommitSyncStatus): void {
  if (data.status === 'success') {
    toast.success(
      `Synced ${data.commits_synced ?? 0} commit(s) and ${data.tags_synced ?? 0} tag(s)`,
    )
  } else if (data.status === 'failed') {
    toast.error(`Commit & tag sync failed: ${data.error ?? 'unknown error'}`)
  }
}

function isActive(state: CommitSyncState | undefined): boolean {
  return state === 'queued' || state === 'running'
}
