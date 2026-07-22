import { useCallback, useEffect, useRef, useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { patchProject } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { applyJsonPatch } from '@/lib/json-patch'
import type {
  LifecycleInvocation,
  PatchOperation,
  Project,
  ProjectMutationResponse,
} from '@/types'

const SCORE_REFRESH_INITIAL_DELAY = 3_000
const SCORE_REFRESH_MAX_ATTEMPTS = 5
const SCORE_REFRESH_BACKOFF_FACTOR = 2

export interface UseProjectPatchResult {
  patch: (
    path: string,
    value: unknown,
    options?: { transferRepository?: boolean },
  ) => Promise<void>
  pendingPath: null | string
  scheduleScoreRefresh: () => void
}

export function useProjectPatch(
  orgSlug: string,
  projectId: string,
): UseProjectPatchResult {
  const qc = useQueryClient()
  const [pendingPath, setPendingPath] = useState<null | string>(null)
  const scoreRefreshTimer = useRef<null | ReturnType<typeof setTimeout>>(null)
  const scoreRefreshAttempt = useRef(0)

  useEffect(() => {
    return () => {
      if (scoreRefreshTimer.current !== null) {
        clearTimeout(scoreRefreshTimer.current)
      }
    }
  }, [])

  const invalidateScoreQueries = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['project', orgSlug, projectId] })
    qc.invalidateQueries({ queryKey: ['scoreTrend', orgSlug, projectId] })
    qc.invalidateQueries({ queryKey: ['scoreTrend90', orgSlug, projectId] })
    qc.invalidateQueries({
      queryKey: ['projectBreakdown', orgSlug, projectId],
    })
    qc.invalidateQueries({ queryKey: ['scoreHistory', orgSlug, projectId] })
    qc.invalidateQueries({
      queryKey: ['scoreHistoryRaw', orgSlug, projectId],
    })
  }, [qc, orgSlug, projectId])

  const scheduleScoreRefresh = useCallback(() => {
    if (scoreRefreshTimer.current !== null) {
      clearTimeout(scoreRefreshTimer.current)
    }
    scoreRefreshAttempt.current = 0

    const attempt = () => {
      scoreRefreshTimer.current = null
      invalidateScoreQueries()
      scoreRefreshAttempt.current += 1
      if (scoreRefreshAttempt.current < SCORE_REFRESH_MAX_ATTEMPTS) {
        const delay =
          SCORE_REFRESH_INITIAL_DELAY *
          SCORE_REFRESH_BACKOFF_FACTOR ** scoreRefreshAttempt.current
        scoreRefreshTimer.current = setTimeout(attempt, delay)
      }
    }

    scoreRefreshTimer.current = setTimeout(attempt, SCORE_REFRESH_INITIAL_DELAY)
  }, [invalidateScoreQueries])

  const patch = useCallback(
    async (
      path: string,
      value: unknown,
      options?: { transferRepository?: boolean },
    ) => {
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

        // Only forward ``options`` when present so a plain patch calls
        // ``patchProject`` with its original 3-arg signature.
        const response: ProjectMutationResponse = options
          ? await patchProject(orgSlug, projectId, [op], options)
          : await patchProject(orgSlug, projectId, [op])
        // Lifecycle plugins (e.g. GitHub repo rename / description sync)
        // run after the project write commits.  Surface failed ones so
        // they're not silent; ``ok``/``skipped`` results are noise from
        // the operator's perspective.
        reportLifecycleFailures(response.lifecycle_results)
        // The server PATCH response may echo fields in a different shape than
        // GET returns (e.g. environments as a map vs. an array). Invalidate
        // so the next read comes from the canonical GET.
        qc.invalidateQueries({ queryKey: key })
        // Activity events are written synchronously — refresh immediately.
        qc.invalidateQueries({
          queryKey: ['events', orgSlug, projectId],
        })
        scheduleScoreRefresh()
      } catch (error) {
        // Rollback optimistic update
        if (optimisticApplied && snapshot !== undefined) {
          qc.setQueryData(key, snapshot)
        }
        toast.error(`Save failed: ${extractApiErrorDetail(error)}`)
        throw error
      } finally {
        setPendingPath(null)
      }
    },
    [qc, orgSlug, projectId, scheduleScoreRefresh],
  )

  return { patch, pendingPath, scheduleScoreRefresh }
}

function buildOp(path: string, value: unknown): PatchOperation {
  if (value === null || value === undefined || value === '') {
    return { op: 'remove', path }
  }
  // `add` upserts on object members: creates the key if missing, replaces
  // it if present. Required so first-time sets for blueprint-defined
  // attributes succeed against an RFC 6902 strict server.
  return { op: 'add', path, value }
}

// Toast the slugs of any lifecycle plugins that reported a ``failed``
// invocation -- the Imbi state change succeeded, but a third-party
// sync (e.g. the GitHub plugin renaming the repo) didn't, and the
// operator needs to know.
function reportLifecycleFailures(
  results: LifecycleInvocation[] | undefined,
): void {
  if (!results || results.length === 0) {
    return
  }
  const failed = results.filter((r) => r.status === 'failed')
  if (failed.length === 0) {
    return
  }
  toast.error(
    `${failed.length} integration${failed.length > 1 ? 's' : ''} failed`,
    {
      description: failed
        .map((r) => `${r.plugin_slug}: ${r.message ?? 'unknown error'}`)
        .join('\n'),
      duration: 10_000,
    },
  )
}
