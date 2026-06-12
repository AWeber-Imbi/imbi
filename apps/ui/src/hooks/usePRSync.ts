import { useEffect, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { PRSyncState, PRSyncStatus } from '@/api/endpoints'
import {
  getProjectPRSyncStatus,
  syncProjectPullRequests,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

const POLL_MS = 3000

// Drives the Project Doctor "Sync PRs" button: enqueues the background
// job and polls the project's PR sync-status while a run is in flight,
// toasting the terminal result so the user gets feedback even though the
// work happens off-request.
// fallow-ignore-next-line complexity
export function usePRSync(
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
    queryFn: ({ signal }): Promise<PRSyncStatus> =>
      getProjectPRSyncStatus(orgSlug, projectId, signal),
    queryKey: ['prSyncStatus', orgSlug, projectId],
    // Poll only while a run is queued/running; settle back to idle.
    refetchInterval: (query) =>
      isActive(query.state.data?.status) ? POLL_MS : false,
  })

  // Toast the terminal result when a poll observes the run leaving the
  // active state. The ref guards against toasting stale state on mount.
  const previous = useRef<PRSyncState | undefined>(undefined)
  // fallow-ignore-next-line complexity
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
    mutationFn: () => syncProjectPullRequests(orgSlug, projectId),
    onError: (err) =>
      toast.error(extractApiErrorDetail(err) ?? 'Failed to start PR sync'),
    onSuccess: (res) => {
      if (res.enqueued) {
        toast.success('PR sync started')
        void queryClient.invalidateQueries({
          queryKey: ['prSyncStatus', orgSlug, projectId],
        })
      } else {
        toast.info('A PR sync is already in progress')
      }
    },
  })

  const isSyncing = mutation.isPending || isActive(statusQuery.data?.status)
  return { isSyncing, sync: mutation.mutate }
}

// Announce a run's terminal outcome once it leaves the active state.
// fallow-ignore-next-line complexity
function announceTerminal(data: PRSyncStatus): void {
  if (data.status === 'success') {
    toast.success(`Synced ${data.prs_synced ?? 0} pull request(s)`)
  } else if (data.status === 'failed') {
    toast.error(`PR sync failed: ${data.error ?? 'unknown error'}`)
  }
}

function isActive(state: PRSyncState | undefined): boolean {
  return state === 'queued' || state === 'running'
}
