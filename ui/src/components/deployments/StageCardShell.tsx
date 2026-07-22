import type { ReactNode } from 'react'

import type { LucideIcon } from 'lucide-react'

import type { ChipColors } from '@/lib/chip-colors'

interface StageCardShellProps {
  accent: ChipColors | null
  /** Right-aligned element in the header strip (e.g. an environment URL). */
  aside?: ReactNode
  children: ReactNode
  icon: LucideIcon
  subtitle?: ReactNode
  title: ReactNode
}

/**
 * Card with a header strip tinted in the environment's derived color —
 * the shared frame for the per-environment deployment cards.
 */
export function StageCardShell({
  accent,
  aside,
  children,
  icon: Icon,
  subtitle,
  title,
}: StageCardShellProps) {
  return (
    <div
      className="border-tertiary bg-primary overflow-hidden rounded-lg border"
      style={accent ? { borderColor: accent.border } : undefined}
    >
      <div
        className="border-tertiary flex items-center gap-3 border-b px-4 py-3"
        style={
          accent
            ? { backgroundColor: accent.bg, borderColor: accent.border }
            : undefined
        }
      >
        <span
          className="bg-primary flex size-8 shrink-0 items-center justify-center rounded-md border"
          style={
            accent
              ? { borderColor: accent.border, color: accent.fg }
              : undefined
          }
        >
          <Icon size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{title}</div>
          {subtitle ? (
            <div
              className="mt-0.5 text-xs"
              style={accent ? { color: accent.fg } : undefined}
            >
              {subtitle}
            </div>
          ) : null}
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
      {children}
    </div>
  )
}
