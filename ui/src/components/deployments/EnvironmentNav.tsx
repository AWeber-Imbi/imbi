import { ArrowUp, Check, GitMerge } from 'lucide-react'

import {
  IntegrationSyncStatus,
  type Readiness,
} from '@/components/deploy/IntegrationSyncStatus'
import { deriveChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'

import type { PipelineStage } from './pipeline'

interface EnvironmentNavProps {
  connectLabel: string
  isDarkMode: boolean
  isSyncing: boolean
  onSelect: (slug: string) => void
  onSync: () => void
  readiness: Readiness
  selectedSlug: null | string
  /** Third-party service powering the deployment plugin. */
  serviceIcon: null | string
  serviceLabel: null | string
  /** Stages in ascending sort order; rendered descending (last env first). */
  stages: PipelineStage[]
}

// fallow-ignore-next-line complexity
export function EnvironmentNav({
  connectLabel,
  isDarkMode,
  isSyncing,
  onSelect,
  onSync,
  readiness,
  selectedSlug,
  serviceIcon,
  serviceLabel,
  stages,
}: EnvironmentNavProps) {
  return (
    <nav className="border-tertiary sticky top-4 self-start rounded-lg border p-2.5">
      <p className="text-tertiary px-2 pt-1 pb-2 text-xs tracking-wider uppercase">
        Pipeline
      </p>
      {[...stages].reverse().map((stage) => {
        const accent = stage.env.label_color
          ? deriveChipColors(stage.env.label_color, isDarkMode)
          : null
        const active = stage.env.slug === selectedSlug
        const version =
          stage.current?.release?.tag ??
          stage.current?.release?.committish.slice(0, 7) ??
          'not deployed'
        return (
          <button
            className={cn(
              'mb-0.5 flex w-full items-center gap-3 rounded-md border border-transparent px-2.5 py-2 text-left transition-colors',
              !active && 'hover:bg-secondary',
            )}
            key={stage.env.slug}
            onClick={() => onSelect(stage.env.slug)}
            style={
              active && accent
                ? { backgroundColor: accent.bg, borderColor: accent.border }
                : undefined
            }
            type="button"
          >
            <span className="min-w-0 flex-1">
              <span
                className={cn(
                  'block text-sm',
                  active ? 'font-semibold' : 'font-medium',
                )}
              >
                {stage.env.name}
              </span>
              <span className="text-tertiary block font-mono text-[11px]">
                {version}
              </span>
            </span>
            <StageBadge accent={accent} stage={stage} />
          </button>
        )
      })}
      <IntegrationSyncStatus
        className="border-tertiary mt-2 w-full justify-between border-t px-2 pt-2.5 pb-1"
        connectLabel={connectLabel}
        isSyncing={isSyncing}
        onSync={onSync}
        readiness={readiness}
        serviceIcon={serviceIcon}
        serviceLabel={serviceLabel}
      />
    </nav>
  )
}

// fallow-ignore-next-line complexity
function StageBadge({
  accent,
  stage,
}: {
  accent: null | ReturnType<typeof deriveChipColors>
  stage: PipelineStage
}) {
  if (stage.kind === 'release' && stage.pendingReleases.length > 0) {
    const newest = stage.pendingReleases[0]
    return (
      <span
        className="bg-secondary inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold"
        style={
          accent ? { backgroundColor: accent.bg, color: accent.fg } : undefined
        }
        title={`Release ${newest.tag} is waiting to deploy here`}
      >
        <GitMerge size={11} />
        {newest.tag}
      </span>
    )
  }
  if (stage.kind === 'promote' && stage.pendingCommits.length > 0) {
    return (
      <span
        className="bg-secondary inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
        style={
          accent ? { backgroundColor: accent.bg, color: accent.fg } : undefined
        }
        title={`${stage.pendingCommits.length} commits waiting to promote here`}
      >
        <ArrowUp size={11} />
        {stage.pendingCommits.length}
      </span>
    )
  }
  if (stage.kind === 'commit') return null
  return (
    <span
      className="border-success text-success flex size-4.5 shrink-0 items-center justify-center rounded-full border"
      title="In sync"
    >
      <Check size={11} strokeWidth={3} />
    </span>
  )
}
