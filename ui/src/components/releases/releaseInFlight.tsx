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
  /**
   * True while cutting a *new* tag must stay inert.
   *
   * Wider than {@link blocked}: a settled failure leaves the page in a
   * state the operator has not answered yet, and offering the next
   * version straight away — over drift that still counts the commits the
   * failed release was meant to ship — invites cutting a second tag on
   * top of an unresolved first. Redeploying the tag that failed stays
   * available, since that is the fix the banner points at.
   */
  cutBlocked: boolean
  /** Hides a settled banner. Terminal states only. */
  dismiss: () => void
  /** When a settled release stopped, so the elapsed clock can freeze. */
  endedAt: null | string
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
  cutBlocked: false,
  dismiss: () => {},
  endedAt: null,
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

/**
 * Phases during which no new tag may be cut.
 *
 * Everything but `idle` and `success`: a release that finished cleanly is
 * the one settled outcome that leaves nothing to answer.
 */
const CUT_BLOCKING: ReadonlySet<ReleaseInFlightPhase> = new Set([
  'adopting',
  'build_failed',
  'building',
  'deploy_failed',
  'deploying',
  'failed',
])

/** Phases in which a release has stopped, for better or worse. */
export const TERMINAL: ReadonlySet<ReleaseInFlightPhase> = new Set([
  'build_failed',
  'deploy_failed',
  'failed',
  'success',
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

/**
 * How long a green banner stands before it retires itself.
 *
 * A success needs no operator decision — the drift below it has already
 * been refetched against the new baseline — so leaving it pinned under the
 * tabs for the rest of the freshness window is just a stale bar the
 * operator has to close by hand. The failure phases keep standing: each
 * one carries an action (unblock, redeploy) and a reason to read it.
 */
const SUCCESS_LINGER_MS = 15 * 1000

interface ReleaseInFlightOptions {
  /** Skip the poll entirely, e.g. before the project id is known. */
  enabled: boolean
  /** Resolves the status' environment *slug* to its display name. */
  envName: (slug: null | string) => null | string
  orgSlug: string
  projectId: string
  /**
   * True while a promote dispatched from this page is being followed.
   *
   * Without it the banner only ever catches a release that was already
   * running when the page mounted: an idle poll turns the refetch
   * interval off, and the cut that happens a minute later never reaches
   * this query — the operator sees the toast and no banner until they
   * reload.
   */
  watching: boolean
}

/** Cut-button text while {@link ReleaseInFlightState.cutBlocked} holds. */
export function cutBlockedLabel(phase: ReleaseInFlightPhase): string {
  if (phase === 'build_failed') return 'Release blocked'
  if (phase === 'deploy_failed' || phase === 'failed') {
    return 'Last release unresolved'
  }
  return 'Release in flight'
}

/**
 * Why a cut button is inert, said next to it.
 *
 * Lives here rather than in either form so the release card and the
 * promote tab cannot drift apart on the same fact.
 */
export function cutBlockedReason(
  phase: ReleaseInFlightPhase,
  tag: null | string,
): string {
  const label = tag ?? 'the release in flight'
  switch (phase) {
    case 'adopting':
      return 'Checking for a release in flight…'
    case 'build_failed':
      return `${label} is blocked — unblock it or fix the build first`
    case 'deploy_failed':
      return `${label} did not deploy — redeploy it, or dismiss the notice`
    case 'failed':
      return `${label} ended unknown — check the run, or dismiss the notice`
    default:
      return `Blocked until ${label} finishes releasing`
  }
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
  watching,
}: ReleaseInFlightOptions): ReleaseInFlightState {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<PromoteStatus>({
    enabled,
    queryFn: ({ signal }) => getPromoteStatus(orgSlug, projectId, signal),
    queryKey: ['release-in-flight', orgSlug, projectId],
    refetchInterval: (q) =>
      watching ||
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

  // A dispatch is news now, not in six seconds, so ask as soon as one is
  // being followed rather than waiting for the first interval tick.
  useEffect(() => {
    if (!watching) return
    void queryClient.invalidateQueries({
      queryKey: ['release-in-flight', orgSlug, projectId],
    })
  }, [watching, orgSlug, projectId, queryClient])

  // Pinned to the first in-flight observation: `updated_at` advances on
  // every phase change, so reading elapsed time off it would restart the
  // clock when `building` becomes `deploying`.
  const startedAtRef = useRef<null | string>(null)
  if (IN_FLIGHT.has(phase)) {
    startedAtRef.current ??= data?.updated_at ?? null
  } else if (phase === 'idle') {
    startedAtRef.current = null
  }

  // A success settles nothing the operator has to answer, so it stops
  // being news shortly after it lands.
  useEffect(() => {
    if (phase !== 'success') return
    const at = data?.updated_at ?? 'dismissed'
    const id = setTimeout(() => setDismissed(at), SUCCESS_LINGER_MS)
    return () => clearTimeout(id)
  }, [phase, data?.updated_at])

  // A settled release moved the drift baseline, so the forms must not
  // re-enable over the state that was true before it ran. Refetching here
  // rather than letting the cards go stale is what makes the released-
  // then-released-again sequence impossible.
  //
  // Every terminal phase, not just `success`: a failed deploy still cut
  // the tag, still wrote a deployment, and still moved the pipeline, so a
  // page that keeps showing the pre-release view is wrong in exactly the
  // way that gets a second tag cut.
  const refreshedRef = useRef<null | string>(null)
  useEffect(() => {
    if (!TERMINAL.has(phase)) return
    const at = data?.updated_at ?? phase
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
    cutBlocked: CUT_BLOCKING.has(phase),
    dismiss,
    endedAt: TERMINAL.has(phase) ? (data?.updated_at ?? null) : null,
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
