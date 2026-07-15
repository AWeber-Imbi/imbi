import { useCallback, useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { patchEnvironmentEdge, patchProject } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

export interface UseEnvironmentEdgePatchResult {
  /** Set/clear one edge attribute on a project x environment edge. */
  patch: (envSlug: string, key: string, value: unknown) => Promise<void>
  /** `${envSlug}/${key}` of the in-flight save, for per-field pending UI. */
  pendingKey: null | string
  /**
   * Replace the project's full environment set. Takes the complete
   * slug -> edge-props map — the backend swaps the DEPLOYED_IN edges
   * wholesale, so omitted environments (or omitted attributes on kept
   * environments) are dropped.
   */
  replaceAll: (map: Record<string, Record<string, unknown>>) => Promise<void>
  /** True while a replaceAll save is in flight. */
  replacing: boolean
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
  const [replacing, setReplacing] = useState(false)

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['project', orgSlug, projectId] })
    qc.invalidateQueries({
      queryKey: ['currentReleases', orgSlug, projectId],
    })
  }, [qc, orgSlug, projectId])

  const patch = useCallback(
    async (envSlug: string, key: string, value: unknown) => {
      const fieldKey = `${envSlug}/${key}`
      setPendingKey(fieldKey)
      try {
        await patchEnvironmentEdge(orgSlug, projectId, envSlug, {
          [key]: value === '' || value === undefined ? null : value,
        })
        invalidate()
      } catch (error) {
        toast.error(`Save failed: ${extractApiErrorDetail(error)}`)
        throw error
      } finally {
        setPendingKey(null)
      }
    },
    [orgSlug, projectId, invalidate],
  )

  const replaceAll = useCallback(
    async (map: Record<string, Record<string, unknown>>) => {
      setReplacing(true)
      try {
        // `add` upserts the member, so the first-ever environment
        // assignment succeeds against an RFC 6902 strict server.
        await patchProject(orgSlug, projectId, [
          { op: 'add', path: '/environments', value: map },
        ])
        invalidate()
      } catch (error) {
        toast.error(`Save failed: ${extractApiErrorDetail(error)}`)
        throw error
      } finally {
        setReplacing(false)
      }
    },
    [orgSlug, projectId, invalidate],
  )

  return { patch, pendingKey, replaceAll, replacing }
}
