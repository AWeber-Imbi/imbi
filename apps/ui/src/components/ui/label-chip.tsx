import type { CSSProperties, ReactNode } from 'react'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'

interface LabelChipProps {
  hex: string
  children: ReactNode
  className?: string
  style?: CSSProperties
  title?: string
}

/**
 * Chip styled with the label-color derivation from the design system:
 * 20% alpha swatch bg, darkened (light) / lightened (dark) fg, 40% alpha border.
 * Used for environment labels, blueprint type chips, and any user-picked color label.
 */
export function LabelChip({
  hex,
  children,
  className,
  style,
  title,
}: LabelChipProps) {
  const { isDarkMode } = useTheme()
  const derived = deriveChipColors(hex, isDarkMode)
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs font-medium',
        className,
      )}
      style={
        derived
          ? {
              backgroundColor: derived.bg,
              color: derived.fg,
              borderColor: derived.border,
              ...style,
            }
          : style
      }
    >
      {children}
    </span>
  )
}
