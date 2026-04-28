/* eslint-disable react-refresh/only-export-components */
import type { CSSProperties } from 'react'

import { ArrowRight } from 'lucide-react'

import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'
import { sortEnvironments } from '@/lib/utils'
import type { Environment } from '@/types'

export interface ReleaseTrainStop {
  // Optional override — treat the stop as done without a value.
  done?: boolean
  environment: Environment
  title?: string
  // Short value displayed next to the environment name (e.g. a version or
  // SHA). Absent means the stop is shown as pending.
  value?: null | string
}

interface ReleaseTrainProps {
  className?: string
  // Compact = ops-log sized; default = project-header sized.
  size?: 'compact' | 'default'
  // Caller decides which environments appear; the component orders them
  // by each environment's sort_order.
  stops: ReleaseTrainStop[]
}

const SIZE_STYLES: Record<
  NonNullable<ReleaseTrainProps['size']>,
  { arrow: string; chip: string; gap: string }
> = {
  compact: {
    arrow: 'h-3 w-3',
    chip: 'rounded px-2 py-0.5 text-[11px] font-mono',
    gap: 'gap-1.5',
  },
  default: {
    arrow: 'h-4 w-4',
    chip: 'rounded-md px-3 py-1.5 text-sm',
    gap: 'gap-2',
  },
}

// Convenience helper: given a project's environments and a map of
// env_slug → value (version/SHA), produce the stops array sorted for the
// train. Environments with no matching value render as pending.
export function buildReleaseTrainStops(
  environments: Environment[] | undefined,
  valueBySlug: Map<string, null | string | undefined>,
): ReleaseTrainStop[] {
  if (!environments?.length) return []
  return sortEnvironments(environments).map((env) => ({
    environment: env,
    value: valueBySlug.get(env.slug) ?? null,
  }))
}

export function ReleaseTrain({
  className,
  size = 'default',
  stops,
}: ReleaseTrainProps) {
  const { isDarkMode } = useTheme()
  const s = SIZE_STYLES[size]
  const ordered = [...stops].sort(
    (a, b) =>
      (a.environment.sort_order ?? 0) - (b.environment.sort_order ?? 0) ||
      a.environment.name.localeCompare(b.environment.name),
  )

  if (ordered.length === 0) return null

  return (
    <div className={cn('flex flex-wrap items-center', s.gap, className)}>
      {ordered.map((stop, idx) => {
        const done = stop.done ?? stop.value != null
        const color = stop.environment.label_color
        const derived =
          done && color ? deriveChipColors(color, isDarkMode) : null
        const style: CSSProperties | undefined = derived
          ? {
              backgroundColor: derived.bg,
              borderColor: derived.border,
              color: derived.fg,
            }
          : undefined
        const title =
          stop.title ??
          `${stop.environment.name}${stop.value ? `: ${stop.value}` : ' · not deployed'}`
        return (
          <span className="flex items-center" key={stop.environment.slug}>
            {idx > 0 ? (
              <ArrowRight
                aria-hidden
                className={cn('mr-2 text-tertiary', s.arrow)}
                style={size === 'compact' ? { marginRight: 6 } : undefined}
              />
            ) : null}
            <span
              className={cn(
                'inline-flex items-center whitespace-nowrap border font-medium',
                s.chip,
                !done &&
                  'border-dashed border-tertiary text-tertiary opacity-60',
              )}
              style={style}
              title={title}
            >
              <span className="font-medium">{stop.environment.name}</span>
              {stop.value ? (
                <span
                  className={cn(
                    'ml-1.5 font-mono',
                    size === 'compact' ? 'text-[11px]' : 'text-xs',
                  )}
                >
                  {stop.value}
                </span>
              ) : null}
            </span>
          </span>
        )
      })}
    </div>
  )
}
