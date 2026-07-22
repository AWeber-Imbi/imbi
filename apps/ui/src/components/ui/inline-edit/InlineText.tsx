import { useCallback, useEffect, useRef } from 'react'

import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { cn } from '@/lib/utils'

import { InlineDisplay } from './InlineDisplay'

export interface InlineTextProps {
  className?: string
  inputClassName?: string
  onCommit: (next: null | string) => Promise<void> | void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  /** Render value in a custom display element; default is a plain span. */
  renderValue?: (value: string) => React.ReactNode
  value: null | string
}

export function InlineText({
  className,
  inputClassName,
  onCommit,
  pending = false,
  placeholder,
  readOnly = false,
  renderValue,
  value,
}: InlineTextProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const handleCommit = useCallback(
    async (next: string) => {
      await onCommit(next === '' ? null : next)
    },
    [onCommit],
  )
  const edit = useInlineEdit<string>({
    initial: value ?? '',
    onCommit: handleCommit,
  })

  useEffect(() => {
    if (edit.isEditing) inputRef.current?.focus()
  }, [edit.isEditing])

  if (!edit.isEditing) {
    const hasValue = !!value
    return (
      <span className={className}>
        <InlineDisplay
          hasValue={hasValue}
          onClick={edit.enter}
          pending={pending}
          placeholder={placeholder}
          readOnly={readOnly}
        >
          {hasValue && (renderValue ? renderValue(value!) : value)}
        </InlineDisplay>
      </span>
    )
  }

  return (
    <span className={className}>
      <Input
        className={cn('h-7 py-1', inputClassName)}
        onBlur={edit.handleBlur}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        ref={inputRef}
        value={edit.draft}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
