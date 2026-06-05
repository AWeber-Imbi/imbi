import { useCallback, useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { patchEnvironmentEdge } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

export interface UseEnvironmentEdgePatchResult {
  /** Set/clear one edge attribute on a project x environment edge. */
  patch: (envSlug: string, key: string, value: unknown) => Promise<void>
  /** `${envSlug}/${key}` of the in-flight save, for per-field pending UI. */
  pendingKey: null | string
}

/**
 * Inline-edit a single DEPLOYED_IN edge attribute for an environment. Hits the
 * targeted edge endpoint (per-key SET/REMOVE — reliable, touches only that
 * edge), then invalidates the project + current-releases queries so the card
 * re-reads canonical values. Empty/undefined values clear the attribute.
 */
export function useEnvironmentEdgePatch(
  orgSlug: string,
  projectId: string,
): UseEnvironmentEdgePatchResult {
  const qc = useQueryClient()
  const [pendingKey, setPendingKey] = useState<null | string>(null)

  const patch = useCallback(
    async (envSlug: string, key: string, value: unknown) => {
      const fieldKey = `${envSlug}/${key}`
      setPendingKey(fieldKey)
      try {
        await patchEnvironmentEdge(orgSlug, projectId, envSlug, {
          [key]: value === '' || value === undefined ? null : value,
        })
        qc.invalidateQueries({ queryKey: ['project', orgSlug, projectId] })
        qc.invalidateQueries({
          queryKey: ['currentReleases', orgSlug, projectId],
        })
      } catch (error) {
        toast.error(`Save failed: ${extractApiErrorDetail(error)}`)
        throw error
      } finally {
        setPendingKey(null)
      }
    },
    [qc, orgSlug, projectId],
  )

  return { patch, pendingKey }
}
