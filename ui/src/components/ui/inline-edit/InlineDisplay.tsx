import { Loader2, Pencil } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface InlineDisplayProps {
  children?: React.ReactNode
  className?: string
  hasValue: boolean
  onClick: () => void
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
}

export function InlineDisplay({
  children,
  className,
  hasValue,
  onClick,
  pending = false,
  placeholder = 'Add…',
  readOnly = false,
}: InlineDisplayProps) {
  const interactive = !readOnly && !pending

  return (
    <span
      className={cn(
        'group inline-flex items-center gap-1.5',
        interactive &&
          'cursor-pointer rounded-sm hover:bg-secondary/40 focus:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        className,
      )}
      onClick={interactive ? onClick : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : -1}
    >
      {pending ? (
        <Loader2 className="text-tertiary size-3 animate-spin" />
      ) : interactive ? (
        <Pencil className="text-tertiary size-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      ) : null}
      {hasValue ? (
        children
      ) : (
        <span className="text-tertiary italic">{placeholder}</span>
      )}
    </span>
  )
}
