import { ChevronDown, Rocket } from 'lucide-react'
import { memo } from 'react'
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
import { deriveChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'
import type { Environment, Project } from '@/types'
import { OperationsLogEntryDetails } from './OperationsLogEntryDetails'
import { OPS_ROW_GRID, OPS_ROW_PAD } from './opsRowLayout'
import {
  absTime,
  cleanDescription,
  cleanName,
  relTime,
  type ReleaseGroup,
} from './opsLogHelpers'

interface Props {
  id: string
  group: ReleaseGroup
  project?: Project
  environmentsBySlug: Map<string, Environment>
  isOpen: boolean
  onToggle: (id: string) => void
  performerDisplayNames: Map<string, string>
}

export const OperationsLogReleaseCard = memo(function OperationsLogReleaseCard({
  id,
  group,
  project,
  environmentsBySlug,
  isOpen,
  onToggle,
  performerDisplayNames,
}: Props) {
  const { isDarkMode } = useTheme()
  const latest = group.latestEntry
  const performer = latest.performed_by ?? latest.recorded_by
  const displayName = performerDisplayNames.get(performer) ?? performer
  const version = group.stops[0]?.entry.version ?? latest.version ?? ''
  const desc = cleanDescription(group.description, version)
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
      value: stop?.entry.version ?? null,
      title: stop
        ? `${env.name}: ${stop.entry.version ?? '—'} · ${absTime(stop.entry.occurred_at)}`
        : `${env.name} · not deployed`,
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
        contentVisibility: 'auto',
        containIntrinsicSize: 'auto 72px',
      }}
    >
      <button
        type="button"
        onClick={() => onToggle(id)}
        aria-expanded={isOpen}
        aria-controls={`ops-log-details-${id}`}
        className={cn(
          'group grid w-full cursor-pointer items-center gap-x-3 gap-y-1 text-left transition-colors',
          OPS_ROW_PAD,
          !isOpen && 'hover:bg-secondary',
        )}
        style={{
          gridTemplateColumns: OPS_ROW_GRID,
          gridTemplateRows: desc ? 'auto auto' : 'auto',
        }}
      >
        <span
          className={cn(
            'self-stretch rounded-r-sm',
            !railColors && 'bg-tertiary',
          )}
          style={{
            ...(railColors ? { backgroundColor: railColors.border } : {}),
            gridColumn: 1,
            gridRow: '1 / -1',
          }}
          aria-hidden
        />
        <span
          className="flex h-[26px] w-[26px] items-center justify-center rounded-md bg-success text-success"
          style={{ gridColumn: 2, gridRow: 1 }}
        >
          <Rocket className="h-3.5 w-3.5" />
        </span>
        <span
          className="truncate text-sm font-medium text-primary"
          style={{ gridColumn: 3, gridRow: 1 }}
          title={projectLabel}
        >
          {projectLabel}
        </span>
        <span
          className="truncate font-mono text-xs text-secondary"
          style={{ gridColumn: 4, gridRow: 1 }}
        >
          {version || '—'}
        </span>
        {desc ? null : (
          <span
            className="min-w-0 truncate text-sm text-tertiary"
            style={{ gridColumn: 5 }}
          >
            —
          </span>
        )}
        <span
          className="flex items-center justify-center"
          style={{ gridColumn: 6, gridRow: '1 / -1' }}
        >
          <ReleaseTrain stops={trainStops} size="compact" />
        </span>
        <span
          className="self-center justify-self-end"
          style={{ gridColumn: 7, gridRow: '1 / -1' }}
          title={displayName}
        >
          <Gravatar
            email={performer}
            size={22}
            className="h-[22px] w-[22px] rounded-full"
          />
        </span>
        <TooltipProvider delayDuration={250}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className="self-center whitespace-nowrap text-right text-xs tabular-nums text-tertiary"
                style={{ gridColumn: 8, gridRow: '1 / -1' }}
              >
                {relTime(latest.occurred_at)}
              </span>
            </TooltipTrigger>
            <TooltipContent>{absTime(latest.occurred_at)}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <span
          className="flex items-center justify-center self-center text-tertiary"
          style={{ gridColumn: 9, gridRow: '1 / -1' }}
        >
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 transition-transform',
              isOpen && 'rotate-180 text-primary',
            )}
          />
        </span>
        {desc ? (
          <span
            className="min-w-0 truncate text-sm text-secondary"
            style={{ gridColumn: '3 / 6', gridRow: 2 }}
          >
            {desc}
          </span>
        ) : null}
      </button>
      {isOpen ? (
        <div
          id={`ops-log-details-${id}`}
          className="border-t border-dashed border-tertiary"
        >
          <OperationsLogEntryDetails entry={latest} />
          <div className="space-y-2 px-4 pb-4 pl-[60px]">
            <div className="text-overline uppercase text-tertiary">
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
                    key={s.entry.environment_slug}
                    className="grid grid-cols-[24px_120px_1fr_auto] items-center gap-3 rounded-md border border-tertiary bg-primary px-3 py-2 text-sm"
                  >
                    <Rocket className="h-3.5 w-3.5 text-tertiary" />
                    <span
                      className="inline-flex items-center justify-center rounded border px-2 py-0.5 text-xs font-medium"
                      style={
                        colors
                          ? {
                              backgroundColor: colors.bg,
                              color: colors.fg,
                              borderColor: colors.border,
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
                          href={s.entry.link}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-0.5 block truncate text-xs text-amber-text hover:underline"
                        >
                          {s.entry.link}
                        </a>
                      ) : null}
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="text-xs text-tertiary">
                        {absTime(s.entry.occurred_at)}
                      </span>
                      <span className="text-xs text-secondary">
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
