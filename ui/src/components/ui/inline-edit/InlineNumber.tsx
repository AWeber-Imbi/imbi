import { useCallback, useEffect, useRef } from 'react'

import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'

import { InlineDisplay } from './InlineDisplay'

export interface InlineNumberProps {
  integer?: boolean
  max?: number
  min?: number
  onCommit: (next: null | number) => Promise<void> | void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  /** Override the display-mode rendering. */
  renderDisplay?: React.ReactNode
  step?: number
  value: null | number
}

export function InlineNumber({
  integer = false,
  max,
  min,
  onCommit,
  pending = false,
  placeholder,
  readOnly = false,
  renderDisplay,
  step,
  value,
}: InlineNumberProps) {
  const ref = useRef<HTMLInputElement>(null)
  const handleCommit = useCallback(
    async (next: string) => {
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
    [onCommit, integer, min, max],
  )
  const edit = useInlineEdit<string>({
    initial: value === null || value === undefined ? '' : String(value),
    onCommit: handleCommit,
  })

  useEffect(() => {
    if (edit.isEditing) ref.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    return (
      <InlineDisplay
        hasValue={value !== null && value !== undefined}
        onClick={edit.enter}
        pending={pending}
        placeholder={placeholder}
        readOnly={readOnly}
      >
        {renderDisplay ??
          (value !== null && value !== undefined ? String(value) : null)}
      </InlineDisplay>
    )
  }

  return (
    <span className="block">
      <Input
        className="h-7 w-32 py-1"
        inputMode={integer ? 'numeric' : 'decimal'}
        max={max}
        min={min}
        onBlur={edit.handleBlur}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        ref={ref}
        step={step}
        type="number"
        value={edit.draft}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
