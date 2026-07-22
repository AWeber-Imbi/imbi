import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { LifecycleSyncSummary } from '@/api/endpoints'
import { syncProjectLifecycle } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

// Project-level lifecycle sync. Re-dispatches on_project_updated (an
// upsert) for the one project, then invalidates the project + its plugins
// so any newly-written links surface.
export function useProjectLifecycleSync(orgSlug: string, projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => syncProjectLifecycle(orgSlug, projectId),
    onError: onSyncError,
    onSuccess: (summary: LifecycleSyncSummary) => {
      toastResult(summary)
      void queryClient.invalidateQueries({
        queryKey: ['project', orgSlug, projectId],
      })
      void queryClient.invalidateQueries({
        queryKey: ['project-plugins', orgSlug, projectId],
      })
    },
  })
}

function onSyncError(err: unknown): void {
  toast.error(extractApiErrorDetail(err) ?? 'Failed to sync lifecycle')
}

function summarize(s: LifecycleSyncSummary): string {
  const parts: string[] = []
  if (s.synced > 0) parts.push(`${s.synced} synced`)
  if (s.skipped > 0) parts.push(`${s.skipped} skipped`)
  if (s.failed > 0) parts.push(`${s.failed} failed`)
  return parts.length > 0 ? parts.join(', ') : 'Nothing to sync'
}

function toastResult(s: LifecycleSyncSummary): void {
  const headline = summarize(s)
  if (s.errors.length > 0) {
    toast.warning(`Lifecycle sync finished with warnings: ${headline}`, {
      description: s.errors
        .slice(0, 5)
        .map((e) => `${e.project_id}: ${e.detail}`)
        .join(' • '),
    })
  } else {
    toast.success(`Lifecycle sync complete: ${headline}`)
  }
}
