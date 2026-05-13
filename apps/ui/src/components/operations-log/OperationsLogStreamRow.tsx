import { memo } from 'react'

import { ChevronDown } from 'lucide-react'

import { Gravatar } from '@/components/ui/gravatar'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import { ENTRY_TYPE_ICONS } from '@/lib/ops-log-icons'
import { cn } from '@/lib/utils'
import type { Environment, OperationsLogRecord, Project } from '@/types'

import { OperationsLogEntryDetails } from './OperationsLogEntryDetails'
import { absTime, cleanDescription, relTime } from './opsLogHelpers'
import { OPS_ROW_GRID, OPS_ROW_PAD } from './opsRowLayout'
import { parseDescription } from './parseDescription'
import { getPluginRenderer } from './plugin-renderers'

interface Props {
  entry: OperationsLogRecord
  environment?: Environment
  id: string
  isOpen: boolean
  onToggle: (id: string) => void
  performerDisplayNames: Map<string, string>
  project?: Project
}

export const OperationsLogStreamRow = memo(function OperationsLogStreamRow({
  entry,
  environment,
  id,
  isOpen,
  onToggle,
  performerDisplayNames,
  project,
}: Props) {
  const { isDarkMode } = useTheme()
  const performer = entry.performed_by ?? entry.recorded_by
  const displayName = performerDisplayNames.get(performer) ?? performer
  const isDeploy = entry.entry_type === 'Deployed'
  const isRestart = entry.entry_type === 'Restarted'
  const parsed = parseDescription(entry)
  const pluginRenderer =
    parsed.kind === 'plugin' ? getPluginRenderer(entry.plugin_slug) : undefined
  const Icon = pluginRenderer?.icon ?? ENTRY_TYPE_ICONS[entry.entry_type]
  const desc =
    parsed.kind === 'plugin'
      ? (pluginRenderer?.label?.({
          action: parsed.action,
          entry,
          payload: parsed.payload,
        }) ??
        parsed.summary ??
        `${entry.plugin_slug}${parsed.action ? ` · ${parsed.action}` : ''}`)
      : cleanDescription(entry.description, entry.version)
  const projectLabel = project?.name ?? entry.project_slug
  const envDisplay = environment?.name ?? entry.environment_slug
  const envColors = environment?.label_color
    ? deriveChipColors(environment.label_color, isDarkMode)
    : null
  const railColor = isRestart ? undefined : envColors?.border

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
            isRestart && 'bg-danger',
            !isRestart && !railColor && 'bg-tertiary',
          )}
          style={{
            ...(railColor ? { backgroundColor: railColor } : {}),
            gridColumn: 1,
            gridRow: '1 / -1',
          }}
        />
        <span
          className={cn(
            'flex size-6.5 items-center justify-center rounded-md',
            isDeploy
              ? 'bg-success text-success'
              : isRestart
                ? 'bg-danger text-danger'
                : 'bg-secondary text-secondary',
          )}
          style={{ gridColumn: 2, gridRow: 1 }}
        >
          <Icon className="size-3.5" />
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
          {entry.version || '—'}
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
          <span
            className="inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium"
            style={
              envColors
                ? {
                    backgroundColor: envColors.bg,
                    borderColor: envColors.border,
                    color: envColors.fg,
                  }
                : undefined
            }
          >
            {envDisplay}
          </span>
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
                {relTime(entry.occurred_at)}
              </span>
            </TooltipTrigger>
            <TooltipContent>{absTime(entry.occurred_at)}</TooltipContent>
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
          <OperationsLogEntryDetails entry={entry} />
        </div>
      ) : null}
    </div>
  )
})
