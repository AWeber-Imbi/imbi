import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'

interface EnvironmentBadgeProps {
  name: string
  slug: string
  label_color?: string | null
}

export function EnvironmentBadge({
  name,
  slug,
  label_color,
}: EnvironmentBadgeProps) {
  const { isDarkMode } = useTheme()
  const derived = label_color ? deriveChipColors(label_color, isDarkMode) : null

  return (
    <span
      key={slug}
      className="rounded px-2 py-1 text-xs font-medium"
      style={
        derived
          ? {
              backgroundColor: derived.bg,
              color: derived.fg,
              border: `1px solid ${derived.border}`,
            }
          : undefined
      }
    >
      {name}
    </span>
  )
}
