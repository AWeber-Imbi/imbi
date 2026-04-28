import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'

interface EnvironmentBadgeProps {
  label_color?: null | string
  name: string
  slug: string
}

export function EnvironmentBadge({
  label_color,
  name,
  slug,
}: EnvironmentBadgeProps) {
  const { isDarkMode } = useTheme()
  const derived = label_color ? deriveChipColors(label_color, isDarkMode) : null

  return (
    <span
      className="rounded px-2 py-1 text-xs font-medium"
      key={slug}
      style={
        derived
          ? {
              backgroundColor: derived.bg,
              border: `1px solid ${derived.border}`,
              color: derived.fg,
            }
          : undefined
      }
    >
      {name}
    </span>
  )
}
