import { useCallback, useEffect, useRef } from 'react'

import { Textarea } from '@/components/ui/textarea'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { cn } from '@/lib/utils'

import { InlineDisplay } from './InlineDisplay'

export interface InlineTextareaProps {
  className?: string
  onCommit: (next: null | string) => Promise<void> | void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  rows?: number
  value: null | string
}

export function InlineTextarea({
  className,
  onCommit,
  pending = false,
  placeholder,
  readOnly = false,
  rows = 3,
  value,
}: InlineTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
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
    if (edit.isEditing) ref.current?.focus()
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
          {hasValue && value}
        </InlineDisplay>
      </span>
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void edit.commit()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      edit.cancel()
    }
    // plain Enter: allow default newline insertion
  }

  return (
    <span className={cn('block', className)}>
      <Textarea
        onBlur={edit.handleBlur}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        ref={ref}
        rows={rows}
        value={edit.draft}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
