import { Pencil, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface InlineDisplayProps {
  hasValue: boolean
  readOnly?: boolean
  pending?: boolean
  onClick: () => void
  className?: string
  placeholder?: string
  children?: React.ReactNode
}

export function InlineDisplay({
  hasValue,
  readOnly = false,
  pending = false,
  onClick,
  className,
  placeholder = 'Add…',
  children,
}: InlineDisplayProps) {
  const interactive = !readOnly && !pending

  return (
    <span
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : -1}
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
      className={cn(
        'group inline-flex items-center gap-1.5',
        interactive &&
          'hover:bg-secondary/40 cursor-pointer rounded-sm focus:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        className,
      )}
    >
      {pending ? (
        <Loader2 className="h-3 w-3 animate-spin text-tertiary" />
      ) : interactive ? (
        <Pencil className="h-3 w-3 text-tertiary opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      ) : null}
      {hasValue ? (
        children
      ) : (
        <span className="italic text-tertiary">{placeholder}</span>
      )}
    </span>
  )
}
