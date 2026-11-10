import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** A toggle button made from a hidden checkbox, so a label finds it. */
export function Chip({
  checked,
  disabled,
  label,
  mono,
  onChange,
  title,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  mono?: boolean
  onChange: (checked: boolean) => void
  title?: string
}) {
  return (
    <label
      className={cn(
        'flex h-8 cursor-pointer items-center rounded-full border border-secondary px-3 text-sm has-checked:border-action has-checked:bg-action has-checked:text-action-foreground has-focus-visible:ring-2 has-focus-visible:ring-ring has-disabled:cursor-not-allowed has-disabled:opacity-50',
        mono && 'font-mono text-xs',
      )}
      title={title}
    >
      <input
        checked={checked}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
  )
}

export function ChipGroup({
  children,
  hint,
  label,
  required = true,
}: {
  children: ReactNode
  hint?: string
  label: string
  required?: boolean
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">
        {label} {required && <span className="text-destructive">*</span>}
        {hint && <span className="text-tertiary ml-2 font-normal">{hint}</span>}
      </legend>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </fieldset>
  )
}
