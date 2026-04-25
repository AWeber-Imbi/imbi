import { LabelChip } from '@/components/ui/label-chip'
import { cn } from '@/lib/utils'
import { colorForTag } from './notesHelpers'
import type { TagRef } from '@/types'

interface Props {
  tag: TagRef
  size?: 'sm' | 'md'
  className?: string
  onClick?: () => void
}

export function NoteTagChip({ tag, size = 'md', className, onClick }: Props) {
  const hex = colorForTag(tag.slug)
  return (
    <LabelChip
      hex={hex}
      className={cn(
        size === 'sm' ? 'px-1.5 py-0 text-[10.5px]' : 'px-2 py-0.5 text-xs',
        onClick && 'cursor-pointer',
        className,
      )}
    >
      <span
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
        className="inline-flex items-center gap-1"
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <span
          aria-hidden
          className="inline-block rounded-full"
          style={{ width: 4, height: 4, backgroundColor: hex }}
        />
        {tag.name}
      </span>
    </LabelChip>
  )
}
