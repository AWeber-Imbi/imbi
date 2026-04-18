import { useEffect, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'

export interface InlineNumberProps {
  value: number | null
  onCommit: (next: number | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  min?: number
  max?: number
  step?: number
  placeholder?: string
  integer?: boolean
  /** Override the display-mode rendering. */
  renderDisplay?: React.ReactNode
}

export function InlineNumber({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  min,
  max,
  step,
  placeholder,
  integer = false,
  renderDisplay,
}: InlineNumberProps) {
  const ref = useRef<HTMLInputElement>(null)
  const edit = useInlineEdit<string>({
    initial: value === null || value === undefined ? '' : String(value),
    onCommit: async (next) => {
      if (next === '') {
        await onCommit(null)
        return
      }
      const parsed = integer ? parseInt(next, 10) : parseFloat(next)
      if (Number.isNaN(parsed)) throw new Error('Not a number')
      if (min !== undefined && parsed < min) throw new Error(`Min is ${min}`)
      if (max !== undefined && parsed > max) throw new Error(`Max is ${max}`)
      await onCommit(parsed)
    },
  })

  useEffect(() => {
    if (edit.isEditing) ref.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    return (
      <InlineDisplay
        hasValue={value !== null && value !== undefined}
        readOnly={readOnly}
        pending={pending}
        onClick={edit.enter}
        placeholder={placeholder}
      >
        {renderDisplay ??
          (value !== null && value !== undefined ? String(value) : null)}
      </InlineDisplay>
    )
  }

  return (
    <span className="block">
      <Input
        ref={ref}
        type="number"
        inputMode={integer ? 'numeric' : 'decimal'}
        min={min}
        max={max}
        step={step}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        onBlur={edit.handleBlur}
        className="h-7 w-32 py-1"
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
