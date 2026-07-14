import { useEffect, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import type { MaintenanceOperation, MaintenanceRunState } from '@/api/endpoints'
import {
  cancelMaintenanceOperation,
  getMaintenanceOperations,
  runMaintenanceOperation,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'

const POLL_MS = 3000
const QUERY_KEY = ['maintenance-operations']

// Drives the admin Maintenance page: fetches the operation registry,
// polls while any global run is in flight, and toasts each operation's
// terminal outcome so the admin gets feedback even though the work
// happens across the server fleet.
export function useMaintenanceOperations() {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryFn: ({ signal }) => getMaintenanceOperations(signal),
    queryKey: QUERY_KEY,
    // Poll only while at least one operation is running.
    refetchInterval: (q) =>
      q.state.data?.some((op) => op.state === 'running') ? POLL_MS : false,
  })

  // Toast each operation's terminal transition (running -> done). The
  // ref guards against toasting historical state on first observation.
  const previous = useRef<Map<string, MaintenanceRunState> | null>(null)
  useEffect(() => {
    const data = query.data
    if (!data) return
    const seen = previous.current
    if (seen) {
      for (const op of data) {
        if (seen.get(op.slug) === 'running' && op.state !== 'running') {
          announceTerminal(op)
        }
      }
    }
    previous.current = new Map(data.map((op) => [op.slug, op.state]))
  }, [query.data])

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: QUERY_KEY })

  // Pending slugs are tracked per call (not via mutation.variables, which
  // only reflects the latest call) so overlapping runs on different rows
  // each keep their own button disabled until their request settles.
  const [pendingRuns, setPendingRuns] = useState<ReadonlySet<string>>(new Set())
  const [pendingCancels, setPendingCancels] = useState<ReadonlySet<string>>(
    new Set(),
  )

  const runMutation = useMutation({
    mutationFn: (slug: string) => runMaintenanceOperation(slug),
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        toast.info('That operation is already running')
        invalidate()
      } else {
        toast.error(
          extractApiErrorDetail(err) ?? 'Failed to start the operation',
        )
      }
    },
    onMutate: (slug) => setPendingRuns((prev) => new Set(prev).add(slug)),
    onSettled: (_res, _err, slug) =>
      setPendingRuns((prev) => withoutSlug(prev, slug)),
    onSuccess: (res) => {
      toast.success(`Operation started for ${res.total} project(s)`)
      invalidate()
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (slug: string) => cancelMaintenanceOperation(slug),
    onError: (err) =>
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to cancel the operation',
      ),
    onMutate: (slug) => setPendingCancels((prev) => new Set(prev).add(slug)),
    onSettled: (_res, _err, slug) =>
      setPendingCancels((prev) => withoutSlug(prev, slug)),
    onSuccess: () => {
      toast.info('Operation cancelled')
      invalidate()
    },
  })

  return {
    cancel: cancelMutation.mutate,
    cancelingSlugs: pendingCancels,
    error: query.error,
    isError: query.isError,
    isLoading: query.isLoading,
    operations: query.data ?? [],
    run: runMutation.mutate,
    runningSlugs: pendingRuns,
  }
}

function announceTerminal(op: MaintenanceOperation): void {
  const failed = op.progress?.failed ?? 0
  if (op.state === 'completed' && failed > 0) {
    toast.warning(`${op.label} completed with ${failed} failure(s)`)
  } else if (op.state === 'completed') {
    toast.success(`${op.label} completed`)
  } else if (op.state === 'cancelled') {
    toast.info(`${op.label} was cancelled`)
  } else if (op.state === 'abandoned') {
    toast.error(`${op.label} was abandoned before completing`)
  }
}

function withoutSlug(
  set: ReadonlySet<string>,
  slug: string,
): ReadonlySet<string> {
  const next = new Set(set)
  next.delete(slug)
  return next
}
