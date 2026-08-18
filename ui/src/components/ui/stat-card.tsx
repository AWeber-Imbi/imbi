export interface StatCardProps {
  label: string
  value: string
  valueColor?: string
}

/**
 * A single headline number above its label, in the flat card shell the
 * reports share. ``valueColor`` takes a CSS variable, never a raw hex.
 */
export function StatCard({ label, value, valueColor }: StatCardProps) {
  return (
    <div className="border-tertiary bg-primary rounded-lg border p-[18px]">
      <div className="text-overline text-tertiary tracking-wide uppercase">
        {label}
      </div>
      <div
        className="mt-2 font-mono text-[28px] leading-none tabular-nums"
        style={{ color: valueColor ?? 'var(--text-color-primary)' }}
      >
        {value}
      </div>
    </div>
  )
}
