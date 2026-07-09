import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { DeploymentResyncSummary } from '@/api/endpoints'
import { resyncProjectDeployments } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { DEEP_RESYNC_LIMIT } from '@/lib/resync'

// Project-level resync. Invalidates the project + currentReleases +
// operationsLog query keys so badges and deploy widgets refresh once
// the backfill completes. Runs a deep backfill (``DEEP_RESYNC_LIMIT``
// deployments per env) so a user-triggered resync also re-resolves
// historical deploy attribution, not just the latest event.
export function useProjectDeploymentResync(orgSlug: string, projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      resyncProjectDeployments(orgSlug, projectId, {
        limit: DEEP_RESYNC_LIMIT,
      }),
    onError: onResyncError,
    onSuccess: (summary: DeploymentResyncSummary) => {
      toastResult(summary)
      void queryClient.invalidateQueries({
        queryKey: ['project', orgSlug, projectId],
      })
      void queryClient.invalidateQueries({
        queryKey: ['currentReleases', orgSlug, projectId],
      })
      void queryClient.invalidateQueries({
        queryKey: ['operationsLog', orgSlug, projectId],
      })
    },
  })
}

function onResyncError(err: unknown): void {
  toast.error(extractApiErrorDetail(err) ?? 'Failed to resync deployments')
}

// Build the "X event(s) recorded • Y release(s) created" headline shown
// on both the project-level and TPS-wide success toasts. Skips counters
// that are zero so the summary stays short on idle remotes.
// fallow-ignore-next-line complexity
function summarize(s: DeploymentResyncSummary): string {
  const parts: string[] = []
  if (s.events_recorded > 0)
    parts.push(`${s.events_recorded} event(s) recorded`)
  if (s.releases_created > 0)
    parts.push(`${s.releases_created} release(s) created`)
  if (s.releases_updated > 0)
    parts.push(`${s.releases_updated} release(s) updated`)
  return parts.length > 0 ? parts.join(', ') : 'Nothing to update'
}

function toastResult(s: DeploymentResyncSummary): void {
  const headline = summarize(s)
  if (s.errors.length > 0) {
    toast.warning(`Resync finished with warnings: ${headline}`, {
      description: s.errors
        .slice(0, 5)
        .map((e) => {
          const env = e.environment ? ` / ${e.environment}` : ''
          const where = e.project_id ? `${e.project_id}${env}` : 'unknown'
          return `${where}: ${e.detail}`
        })
        .join(' • '),
    })
  } else {
    toast.success(`Resync complete: ${headline}`)
  }
}
