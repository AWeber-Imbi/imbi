import { useEffect, useRef } from 'react'
import { Textarea } from '@/components/ui/textarea'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { InlineDisplay } from './InlineDisplay'
import { cn } from '@/lib/utils'

export interface InlineTextareaProps {
  value: string | null
  onCommit: (next: string | null) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  className?: string
  rows?: number
}

export function InlineTextarea({
  value,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder,
  className,
  rows = 3,
}: InlineTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const edit = useInlineEdit<string>({
    initial: value ?? '',
    onCommit: async (next) => {
      await onCommit(next === '' ? null : next)
    },
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
          readOnly={readOnly}
          pending={pending}
          onClick={edit.enter}
          placeholder={placeholder}
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
        ref={ref}
        rows={rows}
        value={edit.draft}
        onChange={(e) => edit.setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={edit.handleBlur}
      />
      {edit.error && (
        <span className="mt-1 block text-xs text-red-600">{edit.error}</span>
      )}
    </span>
  )
}
