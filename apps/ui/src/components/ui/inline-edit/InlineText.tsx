import { useCallback, useEffect, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'
import { cn } from '@/lib/utils'

export interface InlineTextProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  className?: string
  inputClassName?: string
  /** Render value in a custom display element; default is a plain span. */
  renderValue?: (value: string) => React.ReactNode
}

export function InlineText({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  className,
  inputClassName,
  renderValue,
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
          readOnly={readOnly}
          pending={pending}
          onClick={edit.enter}
          placeholder={placeholder}
        >
          {hasValue && (renderValue ? renderValue(value!) : value)}
        </InlineDisplay>
      </span>
    )
  }

  return (
    <span className={className}>
      <Input
        ref={inputRef}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={edit.handleKeyDown}
        onBlur={edit.handleBlur}
        className={cn('h-7 py-1', inputClassName)}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
