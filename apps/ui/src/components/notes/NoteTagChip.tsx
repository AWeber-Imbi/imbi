import { LabelChip } from '@/components/ui/label-chip'
import { cn } from '@/lib/utils'
import type { TagRef } from '@/types'

import { colorForTag } from './notesHelpers'

interface Props {
  className?: string
  onClick?: () => void
  size?: 'md' | 'sm'
  tag: TagRef
}

export function NoteTagChip({ className, onClick, size = 'md', tag }: Props) {
  const hex = colorForTag(tag.slug)
  return (
    <LabelChip
      className={cn(
        size === 'sm' ? 'px-1.5 py-0 text-[10.5px]' : 'px-2 py-0.5 text-xs',
        onClick && 'cursor-pointer',
        className,
      )}
      hex={hex}
    >
      <span
        className="inline-flex items-center gap-1"
        onClick={onClick}
        onKeyDown={
          onClick
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onClick()
                }
              }
            : undefined
        }
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <span
          aria-hidden
          className="inline-block rounded-full"
          style={{ backgroundColor: hex, height: 4, width: 4 }}
        />
        {tag.name}
      </span>
    </LabelChip>
  )
}
