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

  // The backend reports the persistent status of the project's most recent
  // run (any requester), so a toast is only warranted when this user asked
  // for a sync (`watching`) and a poll then observes the run leaving the
  // active state. `onComplete` still fires on any observed active → success
  // transition so background refreshes happen for other users' runs too.
  const watching = useRef(false)
  const previous = useRef<CommitSyncState | undefined>(undefined)
  useEffect(() => {
    const data = statusQuery.data
    if (!data) return
    if (isActive(previous.current) && !isActive(data.status)) {
      if (watching.current) {
        announceTerminal(data)
        watching.current = false
      }
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
      // The user asked for this run (or joined the one already in
      // progress), so watch for its terminal result.
      watching.current = true
      // The POST returning means the backend flipped the run to queued;
      // prime `previous` so a fast job whose first refetch already reads
      // a terminal status still counts as an active → terminal transition.
      previous.current = 'queued'
      if (res.enqueued) {
        toast.success('Commit & tag sync started')
      } else {
        toast.info('A commit & tag sync is already in progress')
      }
      // Refresh even when joining an existing run: a stale cached 'idle'
      // status would otherwise keep refetchInterval off and this client
      // would never observe the run finishing.
      void queryClient.invalidateQueries({
        queryKey: ['commitSyncStatus', orgSlug, projectId],
      })
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
