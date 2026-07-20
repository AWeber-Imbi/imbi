import { useEffect, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { DeploymentSyncState, DeploymentSyncStatus } from '@/api/endpoints'
import {
  getProjectDeploymentSyncStatus,
  resyncProjectDeployments,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { DEEP_RESYNC_LIMIT } from '@/lib/resync'

const POLL_MS = 3000

// Project-level resync, mirroring useCommitSync: the POST enqueues a
// background backfill (deep — ``DEEP_RESYNC_LIMIT`` deployments per env,
// so a user-triggered resync also re-resolves historical deploy
// attribution) and the hook polls the project's sync-status while a run
// is in flight, toasting the terminal result. `onComplete` fires on any
// observed run completing so callers can refresh badges/widgets.
export function useProjectDeploymentResync(
  orgSlug: string,
  projectId: string,
  /** Invoked when a run completes successfully (e.g. to refresh data). */
  onComplete?: () => void,
) {
  const queryClient = useQueryClient()
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  const statusQuery = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }): Promise<DeploymentSyncStatus> =>
      getProjectDeploymentSyncStatus(orgSlug, projectId, signal),
    queryKey: ['deploymentSyncStatus', orgSlug, projectId],
    // Poll only while a run is queued/running; settle back to idle.
    refetchInterval: (query) =>
      isActive(query.state.data?.status) ? POLL_MS : false,
  })

  // The backend reports the persistent status of the project's most recent
  // run (any requester), so a toast is only warranted when this user asked
  // for a resync (`watching`) and a poll then observes the run leaving the
  // active state. `onComplete` still fires on any observed active → success
  // transition so background refreshes happen for other users' runs too.
  const watching = useRef(false)
  const previous = useRef<DeploymentSyncState | undefined>(undefined)
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
    mutationFn: () =>
      resyncProjectDeployments(orgSlug, projectId, {
        limit: DEEP_RESYNC_LIMIT,
      }),
    onError: (err) =>
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to start deployment resync',
      ),
    onSuccess: (res) => {
      // The user asked for this run (or joined the one already in
      // progress), so watch for its terminal result.
      watching.current = true
      if (res.enqueued) {
        // The POST returning means the backend flipped the run to queued;
        // prime `previous` so a fast job whose first refetch already reads
        // a terminal status still counts as an active → terminal transition.
        previous.current = 'queued'
        toast.success('Deployment resync started')
      } else {
        // enqueued:false is ambiguous — debounced (a run really is
        // active) or queueing unavailable (nothing running). Don't prime
        // `previous`: a stale persisted terminal status must not read as
        // an active → terminal transition, and a genuinely active run
        // will be observed by the poll before it finishes.
        toast.info(
          'Deployment resync could not be started — it may already be ' +
            'running, or the queue is temporarily unavailable',
        )
      }
      // Refresh even when joining an existing run: a stale cached 'idle'
      // status would otherwise keep refetchInterval off and this client
      // would never observe the run finishing.
      void queryClient.invalidateQueries({
        queryKey: ['deploymentSyncStatus', orgSlug, projectId],
      })
    },
  })

  const isSyncing = mutation.isPending || isActive(statusQuery.data?.status)
  return { isSyncing, sync: mutation.mutate }
}

// Announce a run's terminal outcome once it leaves the active state.
function announceTerminal(data: DeploymentSyncStatus): void {
  if (data.status === 'success') {
    const headline = summarize(data)
    if ((data.errors ?? 0) > 0) {
      toast.warning(`Resync finished with ${data.errors} error(s): ${headline}`)
    } else {
      toast.success(`Resync complete: ${headline}`)
    }
  } else if (data.status === 'failed') {
    toast.error(`Deployment resync failed: ${data.error ?? 'unknown error'}`)
  }
}

function isActive(state: DeploymentSyncState | undefined): boolean {
  return state === 'queued' || state === 'running'
}

// Build the "X event(s) recorded • Y release(s) created" headline shown
// on the terminal toast. Skips counters that are zero so the summary
// stays short on idle remotes.
// fallow-ignore-next-line complexity
function summarize(s: DeploymentSyncStatus): string {
  const parts: string[] = []
  if ((s.events_recorded ?? 0) > 0)
    parts.push(`${s.events_recorded} event(s) recorded`)
  if ((s.releases_created ?? 0) > 0)
    parts.push(`${s.releases_created} release(s) created`)
  if ((s.releases_updated ?? 0) > 0)
    parts.push(`${s.releases_updated} release(s) updated`)
  return parts.length > 0 ? parts.join(', ') : 'Nothing to update'
}
