import { MessageSquarePlus } from 'lucide-react'

import { Button } from '@/components/ui/button'

export interface SelectionRect {
  bottom: number
  left: number
  top: number
}

interface Props {
  onComment: () => void
  rect: null | SelectionRect
}

/**
 * Floating "Comment" toolbar shown near a text selection inside the article.
 * Positioned fixed to the viewport (the rect comes from getBoundingClientRect).
 * Uses onMouseDown + preventDefault so clicking it doesn't clear the selection.
 */
export function SelectionToolbar({ onComment, rect }: Props) {
  if (!rect) return null
  const above = rect.top > 120
  const top = above ? rect.top - 44 : rect.bottom + 10
  return (
    <div
      className="border-tertiary bg-primary fixed z-50 flex -translate-x-1/2 items-center gap-1 rounded-md border p-1 shadow-md"
      data-selection-toolbar
      style={{ left: rect.left, top }}
    >
      <Button
        className="h-7 gap-1.5 px-2 text-[12px]"
        onClick={onComment}
        onMouseDown={(e) => {
          e.preventDefault()
        }}
        size="sm"
        variant="ghost"
      >
        <MessageSquarePlus className="size-3.5" />
        Comment
      </Button>
    </div>
  )
}
