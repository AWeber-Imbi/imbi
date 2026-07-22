import { toneStyle } from './tone'
import type { Tone } from './tone'

interface StatusChipProps {
  label: string
  tone: Tone
}

interface StatusDotProps {
  /** Diameter in px. */
  size?: number
  tone: Tone
}

/** Pill with a leading dot + status verb, e.g. ● deployed. */
export function StatusChip({ label, tone }: StatusChipProps) {
  const { chip, dotVar } = toneStyle(tone)
  return (
    <span
      className={`inline-flex h-5 items-center gap-1.5 rounded-sm px-2 text-[11px] font-semibold ${chip}`}
    >
      <span className="size-1.5 rounded-full" style={{ background: dotVar }} />
      {label}
    </span>
  )
}

/** Timeline node marker: a tone-colored dot ringed by the surface color. */
export function StatusDot({ size = 12, tone }: StatusDotProps) {
  return (
    <span
      className="bg-primary block shrink-0 rounded-full"
      style={{
        background: toneStyle(tone).dotVar,
        boxShadow: '0 0 0 3px var(--ds-bg-primary)',
        height: size,
        width: size,
      }}
    />
  )
}
