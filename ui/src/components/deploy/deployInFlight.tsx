import { useCallback, useEffect, useRef, useState } from 'react'

import { CheckCircle2, ExternalLink, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import {
  RELEASE_IDLE,
  type ReleaseInFlightState,
} from '@/components/releases/releaseInFlight'
import { sanitizeHttpUrl } from '@/lib/utils'
import type { DeploymentRunStatus } from '@/types'

import type { DeploymentRunStarted } from './DeploymentModal'

export interface DeployInFlightBanner {
  runId: string
  state: ReleaseInFlightState
}

/**
 * How long a green deploy banner stands before it retires itself.
 * Mirrors the release banner's success linger for the same reason: a
 * finished deploy needs no operator decision.
 */
const SUCCESS_LINGER_MS = 15 * 1000

interface DeployRunEntry {
  endedAt: null | string
  envName: string
  label: null | string
  /**
   * Set when the run settled while another project's page was on
   * screen: the origin page isn't there to banner the outcome, so it
   * falls back to the toast the banner replaced.
   */
  notifyToast: boolean
  /** Project the deploy was triggered from; the banner shows only there. */
  originProjectId: string
  runId: string
  runUrl: null | string
  startedAt: string
  status: 'lost' | DeploymentRunStatus
}

interface UseDeployRunBannersResult {
  /** Banners for runs this project's page dispatched, newest last. */
  banners: DeployInFlightBanner[]
  /** Feed to each toast-less watcher so status flips reach the banner. */
  onStatus: (runId: string, status: 'lost' | DeploymentRunStatus) => void
  /** Call from `onRunStarted` for runs that should raise a banner. */
  start: (run: DeploymentRunStarted) => void
}

/**
 * Banner state for direct deploys, the toast-less counterpart to
 * `useReleaseInFlightState`.
 *
 * Where the release banner reads `promote-status` — server-side state a
 * reload can re-adopt — a direct deploy only exists as the
 * `DeploymentRunWatcher` this page mounted, so the state here lives and
 * dies with the page. The gaps that opens are patched with toasts: a
 * run that settles while another project's page is on screen toasts its
 * outcome (the banner belongs to the origin project and isn't visible),
 * and unmounting the page mid-run leaves a "still running" toast behind
 * so the run doesn't vanish without a trace. A reload still forgets the
 * run entirely — the toast it replaced had the same limit.
 */
export function useDeployRunBanners(
  visibleProjectId: string,
): UseDeployRunBannersResult {
  const [entries, setEntries] = useState<DeployRunEntry[]>([])

  const start = useCallback((run: DeploymentRunStarted) => {
    setEntries((prev) =>
      prev.some((e) => e.runId === run.runId)
        ? prev
        : [
            ...prev,
            {
              // A dispatch can answer with a terminal status outright;
              // seed endedAt so the elapsed clock never starts ticking
              // on a run that is already over.
              endedAt: TERMINAL_STATUSES.has(run.initialStatus ?? 'queued')
                ? new Date().toISOString()
                : null,
              envName: run.envName,
              label: run.refLabel ?? null,
              notifyToast: false,
              originProjectId: run.originProjectId,
              runId: run.runId,
              runUrl:
                sanitizeHttpUrl(run.actionUrl ?? run.runUrl ?? null) ?? null,
              startedAt: new Date().toISOString(),
              status: run.initialStatus ?? 'queued',
            },
          ],
    )
  }, [])

  const onStatus = useCallback(
    (runId: string, status: 'lost' | DeploymentRunStatus) => {
      setEntries((prev) => {
        const idx = prev.findIndex(
          (e) => e.runId === runId && e.status !== status,
        )
        // Bail without a new array so a flip on a run this hook does
        // not track cannot re-render the page for nothing.
        if (idx < 0) return prev
        const entry = prev[idx]
        const terminal = TERMINAL_STATUSES.has(status)
        const next = [...prev]
        next[idx] = {
          ...entry,
          endedAt: terminal
            ? (entry.endedAt ?? new Date().toISOString())
            : null,
          notifyToast: terminal && entry.originProjectId !== visibleProjectId,
          status,
        }
        return next
      })
    },
    [visibleProjectId],
  )

  // Retire green banners on their own; failures wait for the operator.
  // Timers live in a ref so a re-render (another run flipping status)
  // cannot restart a success's linger from zero.
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const dismiss = useCallback((runId: string) => {
    const timer = timersRef.current.get(runId)
    if (timer !== undefined) {
      clearTimeout(timer)
      timersRef.current.delete(runId)
    }
    setEntries((prev) => {
      const next = prev.filter((e) => e.runId !== runId)
      return next.length === prev.length ? prev : next
    })
  }, [])
  useEffect(() => {
    const timers = timersRef.current
    for (const entry of entries) {
      if (entry.status !== 'success' || timers.has(entry.runId)) continue
      timers.set(
        entry.runId,
        setTimeout(() => {
          timers.delete(entry.runId)
          dismiss(entry.runId)
        }, SUCCESS_LINGER_MS),
      )
    }
  }, [entries, dismiss])
  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const id of timers.values()) clearTimeout(id)
      timers.clear()
    }
  }, [])

  // Outcomes that landed with the origin page off screen surface as
  // toasts instead — done in an effect, not the state updater, so a
  // re-run cannot toast twice.
  useEffect(() => {
    for (const entry of entries) {
      if (!entry.notifyToast) continue
      terminalToast(entry)
      dismiss(entry.runId)
    }
  }, [entries, dismiss])

  // Unmounting mid-run stops the polling with it, so leave a toast
  // pointing at the workflow run rather than letting the deploy vanish
  // without a trace.
  const entriesRef = useRef(entries)
  entriesRef.current = entries
  useEffect(
    () => () => {
      for (const entry of entriesRef.current) {
        if (TERMINAL_STATUSES.has(entry.status)) continue
        toast.message(`Deployment to ${entry.envName} still running`, {
          action: runAction(entry.runUrl),
          description:
            'Imbi stopped watching when you left the page — check the ' +
            'workflow run for the outcome.',
          icon: <ExternalLink className="size-4" />,
        })
      }
    },
    [],
  )

  return {
    banners: entries
      .filter((e) => e.originProjectId === visibleProjectId && !e.notifyToast)
      .map((entry) => ({
        runId: entry.runId,
        state: toBannerState(entry, () => dismiss(entry.runId)),
      })),
    onStatus,
    start,
  }
}

const TERMINAL_STATUSES: ReadonlySet<'lost' | DeploymentRunStatus> = new Set([
  'cancelled',
  'failure',
  'lost',
  'success',
])

/**
 * Map a run status onto the banner's phase vocabulary. A cancelled run
 * rides the `deploy_failed` phase (same tone, same redeploy affordance)
 * with its own explanation.
 */
function derive(status: 'lost' | DeploymentRunStatus): {
  error: null | string
  phase: ReleaseInFlightState['phase']
} {
  switch (status) {
    case 'cancelled':
      return {
        error: 'The workflow run was cancelled.',
        phase: 'deploy_failed',
      }
    case 'failure':
      return { error: null, phase: 'deploy_failed' }
    case 'lost':
      return { error: null, phase: 'failed' }
    case 'success':
      return { error: null, phase: 'success' }
    default:
      return { error: null, phase: 'deploying' }
  }
}

function runAction(runUrl: null | string) {
  return runUrl
    ? {
        label: 'View run',
        onClick: () => window.open(runUrl, '_blank', 'noopener'),
      }
    : undefined
}

/** The watcher's terminal toasts, for an outcome the banner can't show. */
function terminalToast(entry: DeployRunEntry): void {
  const action = runAction(entry.runUrl)
  if (entry.status === 'success') {
    toast.success(`Deployed to ${entry.envName}`, {
      action,
      icon: <CheckCircle2 className="size-4 text-emerald-500" />,
    })
  } else if (entry.status === 'lost') {
    toast.message(`Lost track of deployment to ${entry.envName}`, {
      action,
      description: 'Status polling failed; check the workflow run directly.',
      icon: <ExternalLink className="size-4" />,
    })
  } else {
    const verb = entry.status === 'cancelled' ? 'cancelled' : 'failed'
    toast.error(`Deployment to ${entry.envName} ${verb}`, {
      action,
      icon: <XCircle className="size-4 text-rose-500" />,
    })
  }
}

function toBannerState(
  entry: DeployRunEntry,
  dismiss: () => void,
): ReleaseInFlightState {
  const { error, phase } = derive(entry.status)
  return {
    ...RELEASE_IDLE,
    dismiss,
    endedAt: entry.endedAt,
    envName: entry.envName,
    error,
    phase,
    runUrl: entry.runUrl,
    startedAt: entry.startedAt,
    tag: entry.label,
  }
}
