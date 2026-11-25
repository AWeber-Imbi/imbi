import { Check } from 'lucide-react'

import { LABEL_SWATCHES } from '@/lib/chip-colors'
import { cn } from '@/lib/utils'

/** Pick a color from the label palette, or no color (`null`). */
export function LabelSwatchPicker({
  label,
  onChange,
  value,
}: {
  label: string
  onChange: (color: null | string) => void
  value: null | string
}) {
  return (
    <div
      aria-label={label}
      className="flex flex-wrap gap-1.5"
      role="radiogroup"
    >
      <SwatchButton
        checked={value === null}
        label="No color"
        onClick={() => onChange(null)}
      />
      {LABEL_SWATCHES.map((s) => (
        <SwatchButton
          checked={value?.toUpperCase() === s.hex}
          hex={s.hex}
          key={s.hex}
          label={s.name}
          onClick={() => onChange(s.hex)}
        />
      ))}
    </div>
  )
}

function SwatchButton({
  checked,
  hex,
  label,
  onClick,
}: {
  checked: boolean
  hex?: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      aria-checked={checked}
      aria-label={label}
      className={cn(
        'flex size-6 items-center justify-center rounded-md border-2',
        checked ? 'border-primary' : 'border-transparent',
        !hex && 'bg-secondary',
      )}
      onClick={onClick}
      role="radio"
      style={hex ? { backgroundColor: hex } : undefined}
      title={label}
      type="button"
    >
      {checked && <Check className={cn('size-3', hex && 'text-white')} />}
    </button>
  )
}
