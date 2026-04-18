import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { patchProject } from '@/api/endpoints'
import { applyJsonPatch } from '@/lib/json-patch'
import { ApiError } from '@/api/client'
import type { PatchOperation, Project } from '@/types'

export interface UseProjectPatchResult {
  patch: (path: string, value: unknown) => Promise<void>
  pendingPath: string | null
}

function buildOp(path: string, value: unknown): PatchOperation {
  if (value === null || value === undefined || value === '') {
    return { op: 'remove', path }
  }
  return { op: 'replace', path, value }
}

export function useProjectPatch(
  orgSlug: string,
  projectId: string,
): UseProjectPatchResult {
  const qc = useQueryClient()
  const [pendingPath, setPendingPath] = useState<string | null>(null)

  const patch = useCallback(
    async (path: string, value: unknown) => {
      const key = ['project', orgSlug, projectId] as const
      const op = buildOp(path, value)
      const snapshot = qc.getQueryData<Project>(key)
      let optimisticApplied = false

      setPendingPath(path)

      try {
        // Apply optimistic update (best-effort; skip if the patch shape
        // cannot be applied locally so the network PATCH still runs).
        if (snapshot) {
          try {
            qc.setQueryData<Project>(
              key,
              applyJsonPatch(snapshot as unknown as Record<string, unknown>, [
                op,
              ]) as unknown as Project,
            )
            optimisticApplied = true
          } catch {
            // Unsupported local patch shape — let the server be the source of truth.
          }
        }

        const result = await patchProject(orgSlug, projectId, [op])
        qc.setQueryData(key, result)
      } catch (error) {
        // Rollback optimistic update
        if (optimisticApplied && snapshot !== undefined) {
          qc.setQueryData(key, snapshot)
        }
        const detail =
          error instanceof ApiError
            ? (error.response as { data?: { detail?: string } } | undefined)
                ?.data?.detail || error.message
            : error instanceof Error
              ? error.message
              : 'Failed to save'
        toast.error(`Save failed: ${detail}`)
        throw error
      } finally {
        setPendingPath(null)
      }
    },
    [qc, orgSlug, projectId],
  )

  return { patch, pendingPath }
}
