import { useCallback, useEffect, useRef, useState } from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'

import { getPromoteStatus, type PromoteStatus } from '@/api/endpoints'
import { sanitizeHttpUrl } from '@/lib/utils'

/**
 * What the page shows, and what it lets the operator do, while a release
 * is running.
 *
 * `adopting` is the state before the first poll answers — on a reload
 * mid-release there is no way to tell "nothing is running" from "we have
 * not asked yet", and guessing `idle` for a single tick re-opens the
 * double-cut this whole feature exists to close.
 */
export type ReleaseInFlightPhase =
  | 'adopting'
  | 'build_failed'
  | 'building'
  | 'deploy_failed'
  | 'deploying'
  | 'failed'
  | 'idle'
  | 'success'

export interface ReleaseInFlightState {
  /** True while every release / deploy affordance must stay inert. */
  blocked: boolean
  /** Hides a settled banner. Terminal states only. */
  dismiss: () => void
  /** Environment the promote is heading for, already resolved to a name. */
  envName: null | string
  error: null | string
  phase: ReleaseInFlightPhase
  /** Sanitized workflow-run URL, or null when the plugin reported none. */
  runUrl: null | string
  /** When the release entered its first in-flight phase. */
  startedAt: null | string
  tag: null | string
}

/** No release running: the value every surface treats as "carry on". */
export const RELEASE_IDLE: ReleaseInFlightState = {
  blocked: false,
  dismiss: () => {},
  envName: null,
  error: null,
  phase: 'idle',
  runUrl: null,
  startedAt: null,
  tag: null,
}

/** Phases during which nothing new may be cut, promoted, or deployed. */
const BLOCKING: ReadonlySet<ReleaseInFlightPhase> = new Set([
  'adopting',
  'build_failed',
  'building',
  'deploying',
])

/** Phases that mean a release is still running. */
const IN_FLIGHT: ReadonlySet<ReleaseInFlightPhase> = new Set([
  'building',
  'deploying',
])

/**
 * How recent a settled promote has to be for its banner to still stand.
 *
 * `promote-status` is a single slot on the Project node: it reports the
 * *last* promote forever, not just a current one. Without a window, every
 * page load would raise a green "Released v1.2.3" banner for a release cut
 * weeks ago — and, worse, a long-resolved `build_failed` would keep the
 * release form disabled with no way to clear it. Ten minutes is long
 * enough to survive a reload while the operator reads the outcome, short
 * enough that it is never load-bearing state.
 */
const SETTLED_WINDOW_MS = 10 * 60 * 1000

interface ReleaseInFlightOptions {
  /** Skip the poll entirely, e.g. before the project id is known. */
  enabled: boolean
  /** Resolves the status' environment *slug* to its display name. */
  envName: (slug: null | string) => null | string
  orgSlug: string
  projectId: string
}

/**
 * Polls `/deployments/promote-status` and publishes one derived
 * "a release is in flight" value to the whole project page.
 *
 * The state this reads already existed — `ReleaseBuildWatcher` polls the
 * same endpoint, and `useAdoptInFlightPromote` picks a running promote up
 * after a reload — but both of them only ever drove a toast, so no
 * affordance on the page knew a release was running. `ReleaseReadyCard`
 * in particular re-enabled its button about a second after a cut, still
 * showing the same drift and the same suggested tag, which makes a second
 * click the obvious next move.
 *
 * Deliberately its own query key rather than the watcher's: sharing
 * `['promote-status', …]` would seed that cache entry at page load with
 * whichever promote ran last, and a watcher mounting later reads it
 * synchronously — settling against the previous promote's outcome before
 * its own first fetch resolves. `useAdoptInFlightPromote` keeps its own
 * key for the same reason.
 */
export function useReleaseInFlightState({
  enabled,
  envName,
  orgSlug,
  projectId,
}: ReleaseInFlightOptions): ReleaseInFlightState {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<PromoteStatus>({
    enabled,
    queryFn: ({ signal }) => getPromoteStatus(orgSlug, projectId, signal),
    queryKey: ['release-in-flight', orgSlug, projectId],
    refetchInterval: (q) =>
      IN_FLIGHT.has((q.state.data?.status ?? 'idle') as ReleaseInFlightPhase)
        ? 6000
        : false,
    refetchIntervalInBackground: false,
    // A status cached from a previous visit says nothing about now, and
    // catching a release that started while this page was unmounted is
    // the whole point.
    refetchOnMount: 'always',
    retry: 3,
    staleTime: 0,
  })

  const phase = derivePhase(data, enabled && isLoading)
  const [dismissed, setDismissed] = useState<null | string>(null)
  const dismiss = useCallback(
    () => setDismissed(data?.updated_at ?? 'dismissed'),
    [data?.updated_at],
  )

  // Pinned to the first in-flight observation: `updated_at` advances on
  // every phase change, so reading elapsed time off it would restart the
  // clock when `building` becomes `deploying`.
  const startedAtRef = useRef<null | string>(null)
  if (IN_FLIGHT.has(phase)) {
    startedAtRef.current ??= data?.updated_at ?? null
  } else if (phase === 'idle') {
    startedAtRef.current = null
  }

  // A finished release moved the drift baseline, so the form must not
  // re-enable over the tag that was just cut. Refetching here rather than
  // letting the card go stale is what makes the released-then-released-
  // again sequence impossible.
  const refreshedRef = useRef<null | string>(null)
  useEffect(() => {
    if (phase !== 'success') return
    const at = data?.updated_at ?? 'success'
    if (refreshedRef.current === at) return
    refreshedRef.current = at
    void queryClient.invalidateQueries({
      predicate: (q) => q.queryKey.includes(projectId),
    })
  }, [phase, data?.updated_at, projectId, queryClient])

  const key = data?.updated_at ?? 'dismissed'
  if (phase === 'idle' || dismissed === key) return RELEASE_IDLE
  return {
    blocked: BLOCKING.has(phase),
    dismiss,
    envName: envName(data?.environment ?? null),
    error: data?.error ?? null,
    phase,
    runUrl: sanitizeHttpUrl(data?.artifact_run_url) ?? null,
    startedAt: startedAtRef.current ?? data?.updated_at ?? null,
    tag: data?.tag ?? null,
  }
}

/**
 * Map a `promote-status` reading onto a banner phase.
 *
 * A settled status older than {@link SETTLED_WINDOW_MS} reads as `idle`:
 * the endpoint reports the last promote indefinitely, and an ancient
 * outcome is history, not a thing happening now.
 */
function derivePhase(
  data: PromoteStatus | undefined,
  loading: boolean,
): ReleaseInFlightPhase {
  if (loading || !data) return loading ? 'adopting' : 'idle'
  const status = data.status
  if (status === 'idle') return 'idle'
  if (status === 'building' || status === 'deploying') return status
  return isRecent(data.updated_at) ? status : 'idle'
}

function isRecent(updatedAt: null | string | undefined): boolean {
  if (!updatedAt) return false
  const at = Date.parse(updatedAt)
  return Number.isFinite(at) && Date.now() - at < SETTLED_WINDOW_MS
}
