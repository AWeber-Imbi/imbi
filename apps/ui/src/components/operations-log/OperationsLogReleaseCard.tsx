import { memo } from 'react'

import { ChevronDown, Rocket } from 'lucide-react'

import { Gravatar } from '@/components/ui/gravatar'
import {
  ReleaseTrain,
  type ReleaseTrainStop,
} from '@/components/ui/release-train'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useTheme } from '@/contexts/ThemeContext'
import { usePluginOpsLogTemplates } from '@/hooks/usePluginOpsLogTemplates'
import { deriveChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'
import type { Environment, Project } from '@/types'

import { OperationsLogEntryDetails } from './OperationsLogEntryDetails'
import { absTime, cleanName, type ReleaseGroup, relTime } from './opsLogHelpers'
import { OPS_ROW_GRID, OPS_ROW_PAD } from './opsRowLayout'
import { renderEntryLabel } from './renderEntryLabel'

interface Props {
  environmentsBySlug: Map<string, Environment>
  group: ReleaseGroup
  id: string
  isOpen: boolean
  onToggle: (id: string) => void
  performerDisplayNames: Map<string, string>
  project?: Project
}

export const OperationsLogReleaseCard = memo(function OperationsLogReleaseCard({
  environmentsBySlug,
  group,
  id,
  isOpen,
  onToggle,
  performerDisplayNames,
  project,
}: Props) {
  const { isDarkMode } = useTheme()
  const { templates } = usePluginOpsLogTemplates()
  const latest = group.latestEntry
  const performer = latest.performed_by ?? latest.recorded_by
  const displayName = performerDisplayNames.get(performer) ?? performer
  const version = group.stops[0]?.entry.version ?? latest.version ?? ''
  const desc = renderEntryLabel(latest, {
    environment: environmentsBySlug.get(latest.environment_slug),
    performerDisplayName: displayName,
    project,
    templates,
  })
  const projectLabel = project?.name ?? group.project_slug

  // Pipeline = this project's own environments, unioned with any
  // environments that actually received a deploy in this release group
  // (so an out-of-pipeline prod deploy still shows in the train instead
  // of leaving Testing/Staging pending with no Production chip).
  const stopByEnvSlug = new Map(
    group.stops.map((s) => [s.entry.environment_slug, s]),
  )
  const envBySlug = new Map<string, Environment>()
  for (const env of project?.environments ?? []) envBySlug.set(env.slug, env)
  for (const s of group.stops) {
    const slug = s.entry.environment_slug
    if (envBySlug.has(slug)) continue
    const env = environmentsBySlug.get(slug)
    if (env) envBySlug.set(slug, env)
  }
  const trainEnvironments: Environment[] = Array.from(envBySlug.values())

  const trainStops: ReleaseTrainStop[] = trainEnvironments.map((env) => {
    const stop = stopByEnvSlug.get(env.slug)
    return {
      environment: env,
      title: stop
        ? `${env.name}: ${stop.entry.version ?? '—'} · ${absTime(stop.entry.occurred_at)}`
        : `${env.name} · not deployed`,
      value: stop?.entry.version ?? null,
    }
  })

  // Rail colour: the highest-sort_order environment the release has
  // reached. Zero hard-coded env names.
  const reachedEnvs = group.stops
    .map((s) => environmentsBySlug.get(s.entry.environment_slug))
    .filter((e): e is Environment => !!e)
    .sort((a, b) => (b.sort_order ?? 0) - (a.sort_order ?? 0))
  const railColors = reachedEnvs[0]?.label_color
    ? deriveChipColors(reachedEnvs[0]!.label_color!, isDarkMode)
    : null

  return (
    <div
      className={cn(
        'border-b border-tertiary last:border-b-0',
        isOpen && 'bg-secondary',
      )}
      style={{
        containIntrinsicSize: 'auto 72px',
        contentVisibility: 'auto',
      }}
    >
      <button
        aria-controls={`ops-log-details-${id}`}
        aria-expanded={isOpen}
        className={cn(
          'group grid w-full cursor-pointer items-center gap-x-3 gap-y-1 text-left transition-colors',
          OPS_ROW_PAD,
          !isOpen && 'hover:bg-secondary',
        )}
        onClick={() => onToggle(id)}
        style={{
          gridTemplateColumns: OPS_ROW_GRID,
          gridTemplateRows: desc ? 'auto auto' : 'auto',
        }}
        type="button"
      >
        <span
          aria-hidden
          className={cn(
            'self-stretch rounded-r-sm',
            !railColors && 'bg-tertiary',
          )}
          style={{
            ...(railColors ? { backgroundColor: railColors.border } : {}),
            gridColumn: 1,
            gridRow: '1 / -1',
          }}
        />
        <span
          className="bg-success text-success flex size-6.5 items-center justify-center rounded-md"
          style={{ gridColumn: 2, gridRow: 1 }}
        >
          <Rocket className="size-3.5" />
        </span>
        <span
          className="text-primary truncate text-sm font-medium"
          style={{ gridColumn: 3, gridRow: 1 }}
          title={projectLabel}
        >
          {projectLabel}
        </span>
        <span
          className="text-secondary truncate font-mono text-xs"
          style={{ gridColumn: 4, gridRow: 1 }}
        >
          {version || '—'}
        </span>
        {desc ? null : (
          <span
            className="text-tertiary min-w-0 truncate text-sm"
            style={{ gridColumn: 5 }}
          >
            —
          </span>
        )}
        <span
          className="flex items-center justify-center"
          style={{ gridColumn: 6, gridRow: '1 / -1' }}
        >
          <ReleaseTrain size="compact" stops={trainStops} />
        </span>
        <span
          className="self-center justify-self-end"
          style={{ gridColumn: 7, gridRow: '1 / -1' }}
          title={displayName}
        >
          <Gravatar
            className="size-[22px] rounded-full"
            email={performer}
            size={22}
          />
        </span>
        <TooltipProvider delayDuration={250}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className="text-tertiary self-center text-right text-xs whitespace-nowrap tabular-nums"
                style={{ gridColumn: 8, gridRow: '1 / -1' }}
              >
                {relTime(latest.occurred_at)}
              </span>
            </TooltipTrigger>
            <TooltipContent>{absTime(latest.occurred_at)}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <span
          className="text-tertiary flex items-center justify-center self-center"
          style={{ gridColumn: 9, gridRow: '1 / -1' }}
        >
          <ChevronDown
            className={cn(
              'size-3.5 transition-transform',
              isOpen && 'rotate-180 text-primary',
            )}
          />
        </span>
        {desc ? (
          <span
            className="text-secondary min-w-0 truncate text-sm"
            style={{ gridColumn: '3 / 6', gridRow: 2 }}
          >
            {desc}
          </span>
        ) : null}
      </button>
      {isOpen ? (
        <div
          className="border-tertiary border-t border-dashed"
          id={`ops-log-details-${id}`}
        >
          <OperationsLogEntryDetails entry={latest} />
          <div className="space-y-2 px-4 pb-4 pl-15">
            <div className="text-overline text-tertiary uppercase">
              Promotion timeline
            </div>
            {group.stops
              .slice()
              .sort((a, b) => {
                const ea = environmentsBySlug.get(a.entry.environment_slug)
                const eb = environmentsBySlug.get(b.entry.environment_slug)
                return (ea?.sort_order ?? 0) - (eb?.sort_order ?? 0)
              })
              .map((s) => {
                const env = environmentsBySlug.get(s.entry.environment_slug)
                const colors = env?.label_color
                  ? deriveChipColors(env.label_color, isDarkMode)
                  : null
                return (
                  <div
                    className="border-tertiary bg-primary grid grid-cols-[24px_120px_1fr_auto] items-center gap-3 rounded-md border px-3 py-2 text-sm"
                    key={s.entry.environment_slug}
                  >
                    <Rocket className="text-tertiary size-3.5" />
                    <span
                      className="inline-flex items-center justify-center rounded border px-2 py-0.5 text-xs font-medium"
                      style={
                        colors
                          ? {
                              backgroundColor: colors.bg,
                              borderColor: colors.border,
                              color: colors.fg,
                            }
                          : undefined
                      }
                    >
                      {env?.name ?? s.entry.environment_slug}
                    </span>
                    <div className="min-w-0">
                      <div className="font-mono text-xs">
                        {s.entry.version || '—'}
                      </div>
                      {s.entry.link ? (
                        <a
                          className="text-amber-text mt-0.5 block truncate text-xs hover:underline"
                          href={s.entry.link}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {s.entry.link}
                        </a>
                      ) : null}
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="text-tertiary text-xs">
                        {absTime(s.entry.occurred_at)}
                      </span>
                      <span className="text-secondary text-xs">
                        {performerDisplayNames.get(
                          s.entry.performed_by ?? s.entry.recorded_by,
                        ) ??
                          cleanName(
                            s.entry.performed_by ?? s.entry.recorded_by,
                          )}
                      </span>
                    </div>
                  </div>
                )
              })}
          </div>
        </div>
      ) : null}
    </div>
  )
})
