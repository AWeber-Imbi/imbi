import type { ReactNode } from 'react'

import type { ProjectSchemaSectionProperty } from '@/api/endpoints'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { getIcon } from '@/lib/icons'
import {
  applyDisplayFormat,
  COLOR_TEXT,
  formatFieldValue,
} from '@/lib/project-field-formatting'
import { resolveColor, resolveIcon, type XUiMaps } from '@/lib/ui-maps'

interface AttributeValueProps {
  /** Blueprint schema definition driving formatting + x-ui color/icon maps. */
  def?: ProjectSchemaSectionProperty
  /** Rendered when the value is empty/unset. Defaults to `null`. */
  fallback?: ReactNode
  /** The raw attribute value (string/number/bool/etc.) as stored. */
  rawValue: unknown
}

/**
 * Renders an attribute value with the shared display logic used across the
 * app: schema-aware formatting (`formatFieldValue`) plus `x-ui` color/icon
 * resolution (exact map / numeric range / age threshold) and a hover tooltip
 * with the full timestamp for date fields. Returns `null` when there is no
 * value so callers can supply their own empty state.
 *
 * Used by the project-attributes section and the per-environment edge
 * attributes on the project overview.
 */
// fallow-ignore-next-line complexity
export function AttributeValue({
  def,
  fallback = null,
  rawValue,
}: AttributeValueProps) {
  const value = formatFieldValue(rawValue, def)
  if (value === null) return fallback

  // Optional human-readable transform (e.g. ``in_progress`` -> ``In
  // Progress``). Applied to the display string only; color/icon resolution
  // below still keys off the raw value.
  const displayValue = applyDisplayFormat(value, def?.['x-display'])

  const uiMaps = toUiMaps(def)
  const mappedColor = resolveColor(uiMaps, rawValue)
  const mappedIcon = resolveIcon(uiMaps, rawValue)
  const Icon = mappedIcon ? getIcon(mappedIcon) : null
  const colorClass = mappedColor
    ? (COLOR_TEXT[mappedColor] ?? 'text-primary')
    : 'text-primary'

  const isDate = def?.format === 'date-time' || def?.format === 'date'
  const title =
    isDate && rawValue != null
      ? new Date(String(rawValue)).toLocaleString()
      : undefined

  return (
    <span className="flex items-center gap-1.5">
      {Icon && <Icon className={`size-3.5 shrink-0 ${colorClass}`} />}
      {title ? (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className={`text-sm ${colorClass} cursor-help underline decoration-dotted`}
              >
                {displayValue}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p>{title}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        <span className={`text-sm ${colorClass}`}>{displayValue}</span>
      )}
    </span>
  )
}

function toUiMaps(def?: ProjectSchemaSectionProperty): XUiMaps {
  const xUi = def?.['x-ui']
  if (!xUi) return {}
  return {
    colorAge: xUi['color-age'],
    colorMap: xUi['color-map'],
    colorRange: xUi['color-range'],
    iconAge: xUi['icon-age'],
    iconMap: xUi['icon-map'],
    iconRange: xUi['icon-range'],
  }
}
