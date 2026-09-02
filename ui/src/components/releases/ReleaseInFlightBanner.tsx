import { useEffect, useState } from 'react'

import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  Rocket,
  TriangleAlert,
  X,
  XCircle,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import {
  type ReleaseInFlightPhase,
  type ReleaseInFlightState,
  TERMINAL,
} from './releaseInFlight'

/**
 * What kind of operation the banner narrates. A promote walks
 * Building → Deploying → Released; a release-only cut (library / image)
 * has no rollout, so it is Building → Released; a direct deploy has no
 * build phase, so its train is just Deploying → Deployed.
 */
export type InFlightKind = 'deploy' | 'promote' | 'release'

/** The train the banner walks while the operation runs. */
const PHASES: Record<InFlightKind, readonly string[]> = {
  deploy: ['Deploying', 'Deployed'],
  promote: ['Building', 'Deploying', 'Released'],
  release: ['Building', 'Released'],
}

const PHASE_INDEX: Record<
  InFlightKind,
  Partial<Record<ReleaseInFlightPhase, number>>
> = {
  deploy: { deploying: 0, success: 1 },
  promote: { building: 0, deploying: 1, success: 2 },
  release: { building: 0, success: 1 },
}

interface ReleaseInFlightBannerProps {
  kind: InFlightKind
  /** Sends the operator to the tab where a redeploy can be dispatched. */
  onRedeploy: () => void
  onUnblock: (tag: string) => void
  state: ReleaseInFlightState
  unblockPending: boolean
}

type Tone = 'amber' | 'danger' | 'muted' | 'success'

/**
 * Page-level notice that a release is running, pinned under the tabs.
 *
 * A banner rather than a toast on purpose. The toast the promote already
 * raises is transient, corner-anchored, and dismissible — none of which
 * suit a fact that has to stay true for the several minutes it takes a
 * release build to run, and that every affordance below it is being
 * disabled on the strength of. Whenever the release form is inert, the
 * reason is on screen.
 */
export function ReleaseInFlightBanner({
  kind,
  onRedeploy,
  onUnblock,
  state,
  unblockPending,
}: ReleaseInFlightBannerProps) {
  const { envName, error, phase, runUrl, tag } = state
  if (phase === 'idle') return null

  const label = tag ?? (kind === 'deploy' ? 'this deployment' : 'this release')
  if (phase === 'adopting') {
    return (
      <BannerShell tone="muted">
        <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
        <div className="min-w-0 flex-1 text-sm">
          Checking for a release in flight…
        </div>
      </BannerShell>
    )
  }

  return (
    <BannerShell tone={TONE[phase]}>
      <PhaseIcon phase={phase} />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-sm font-semibold">
            {headline(kind, phase, label, envName)}
          </span>
          <Elapsed since={state.startedAt} until={state.endedAt} />
        </div>
        <span className="text-xs leading-relaxed opacity-90">
          {error ?? DETAIL[kind][phase]}
        </span>
        {PHASE_INDEX[kind][phase] === undefined ? null : (
          <PhaseTrain
            active={PHASE_INDEX[kind][phase] ?? 0}
            phases={PHASES[kind]}
          />
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {phase === 'build_failed' && tag ? (
          <Button
            className="h-7 px-2.5 text-xs"
            disabled={unblockPending}
            onClick={() => onUnblock(tag)}
            size="sm"
            type="button"
            variant="outline"
          >
            {`Unblock ${tag}`}
          </Button>
        ) : null}
        {phase === 'deploy_failed' ? (
          <Button
            className="h-7 px-2.5 text-xs"
            onClick={onRedeploy}
            size="sm"
            type="button"
            variant="outline"
          >
            <Rocket className="mr-1 size-3.5" />
            {`Redeploy ${label}`}
          </Button>
        ) : null}
        {runUrl ? (
          <a
            className="inline-flex items-center gap-1 text-xs font-medium hover:underline"
            href={runUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            <ExternalLink className="size-3.5" />
            {kind === 'deploy' ? 'View run' : 'View build'}
          </a>
        ) : null}
        {TERMINAL.has(phase) ? (
          <button
            aria-label="Dismiss"
            className="hover:bg-secondary rounded p-1"
            onClick={state.dismiss}
            type="button"
          >
            <X className="size-3.5" />
          </button>
        ) : null}
      </div>
    </BannerShell>
  )
}

const TONE: Record<ReleaseInFlightPhase, Tone> = {
  adopting: 'muted',
  build_failed: 'danger',
  building: 'amber',
  deploy_failed: 'danger',
  deploying: 'amber',
  failed: 'amber',
  idle: 'muted',
  success: 'success',
}

const TONE_CLASS: Record<Tone, string> = {
  amber: 'border-amber-border bg-amber-bg text-amber-text',
  danger: 'border-danger bg-danger text-danger',
  muted: 'border-tertiary text-tertiary',
  success: 'border-success bg-success text-success',
}

const RELEASE_DETAIL: Record<ReleaseInFlightPhase, string> = {
  adopting: '',
  build_failed:
    'The tag is blocked. Fix the build and release a new version, or ' +
    'unblock this one to retry it.',
  building: 'The release workflow is cutting the tag and building it.',
  deploy_failed:
    'The build was green, so the release is not blocked — redeploy this ' +
    'tag once the cause is fixed.',
  deploying: 'The build is green; Imbi is rolling the release out.',
  failed:
    'Last promote outcome unknown — confirm the run before cutting ' +
    'again. The tag was not blocked, so it can still be deployed.',
  idle: '',
  success: 'Release complete. The drift below reflects the new baseline.',
}

const DETAIL: Record<InFlightKind, Record<ReleaseInFlightPhase, string>> = {
  deploy: {
    adopting: '',
    build_failed: '',
    building: '',
    deploy_failed:
      'Check the workflow run, fix the cause, and redeploy the version.',
    deploying: 'Imbi is rolling the deployment out.',
    failed: 'Status polling failed; check the workflow run directly.',
    idle: '',
    success: 'Deployment complete.',
  },
  promote: RELEASE_DETAIL,
  release: RELEASE_DETAIL,
}

function BannerShell({
  children,
  tone,
}: {
  children: React.ReactNode
  tone: Tone
}) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-lg border px-4 py-3',
        TONE_CLASS[tone],
      )}
      role="status"
    >
      {children}
    </div>
  )
}

/**
 * "4m 12s", ticking once a second while the release runs.
 *
 * `until` freezes it: once the release has stopped the number is how long
 * it took, not a clock still running on a finished thing.
 */
function Elapsed({
  since,
  until,
}: {
  since: null | string
  until: null | string
}) {
  const started = since ? Date.parse(since) : Number.NaN
  const ended = until ? Date.parse(until) : Number.NaN
  const frozen = Number.isFinite(ended)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!Number.isFinite(started) || frozen) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [started, frozen])
  if (!Number.isFinite(started)) return null
  const seconds = Math.max(
    0,
    Math.floor(((frozen ? ended : now) - started) / 1000),
  )
  // Adopted after the fact: start and end are the same reading, and "0s"
  // for a release that took minutes is worse than no number at all.
  if (frozen && seconds === 0) return null
  const minutes = Math.floor(seconds / 60)
  return (
    <span className="font-mono text-xs opacity-75">
      {minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`}
    </span>
  )
}

function headline(
  kind: InFlightKind,
  phase: ReleaseInFlightPhase,
  label: string,
  envName: null | string,
): string {
  const target = envName ? ` to ${envName}` : ''
  switch (phase) {
    case 'build_failed':
      return `Release build for ${label} failed`
    case 'building':
      return `Building release ${label}…`
    case 'deploy_failed':
      return `Deploying ${label}${target} failed`
    case 'deploying':
      return `Deploying ${label}${target}…`
    case 'failed':
      return kind === 'deploy'
        ? `Lost track of deploying ${label}${target}`
        : `Lost track of the release for ${label}`
    default:
      return kind === 'deploy'
        ? `Deployed ${label}${target}`
        : `Released ${label}${target}`
  }
}

function PhaseIcon({ phase }: { phase: ReleaseInFlightPhase }) {
  if (phase === 'building' || phase === 'deploying') {
    return <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
  }
  if (phase === 'success') {
    return <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
  }
  if (phase === 'failed') {
    return <TriangleAlert className="mt-0.5 size-4 shrink-0" />
  }
  return <XCircle className="mt-0.5 size-4 shrink-0" />
}

/** The kind's phase train, with everything before `active` done. */
function PhaseTrain({
  active,
  phases,
}: {
  active: number
  phases: readonly string[]
}) {
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[11px] font-medium">
      {phases.map((name, idx) => (
        <li className="flex items-center gap-1.5" key={name}>
          {idx > 0 ? <span aria-hidden="true">→</span> : null}
          <span
            className={cn(
              'rounded border px-1.5 py-0.5',
              idx <= active
                ? 'border-current'
                : 'border-dashed border-current opacity-50',
            )}
          >
            {name}
          </span>
        </li>
      ))}
    </ol>
  )
}
