import { LabelChip } from '@/components/ui/label-chip'
import type { PackageEnvironmentChip } from '@/types'

interface EnvironmentChipsProps {
  environments: PackageEnvironmentChip[]
  showCounts?: boolean
}

/** Fallback swatch for an environment with no configured label color. */
const NEUTRAL = '#7A7873'

/**
 * Environments a version is currently deployed into, in the label color
 * the environment itself carries so the chips read the same here as on
 * the project screens.
 */
export function EnvironmentChips({
  environments,
  showCounts,
}: EnvironmentChipsProps) {
  if (environments.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {environments.map((env) => (
        <LabelChip hex={env.label_color ?? NEUTRAL} key={env.slug}>
          {env.name}
          {showCounts && (
            <span className="ml-1 font-mono tabular-nums opacity-70">
              {env.count}
            </span>
          )}
        </LabelChip>
      ))}
    </span>
  )
}
