import type { ReactNode } from 'react'

import { LabelChip } from '@/components/ui/label-chip'
import { cn } from '@/lib/utils'

/** The fields of an org tag that a chip shows. */
export interface ChipTag {
  color?: null | string
  name: string
  slug: string
}

/** A tag as a label chip in the tag color, or neutral with no color. */
export function TagChip({
  children,
  size = 'md',
  tag,
}: {
  children?: ReactNode
  size?: 'md' | 'sm'
  tag: ChipTag
}) {
  return (
    <LabelChip
      className={cn(
        size === 'sm' && 'px-1.5 py-0 text-[10.5px]',
        !tag.color && 'border-tertiary text-secondary',
      )}
      hex={tag.color ?? ''}
    >
      {tag.name}
      {children}
    </LabelChip>
  )
}

export function TagChips({ tags }: { tags: ChipTag[] }) {
  if (tags.length === 0) return <span className="text-tertiary text-sm">—</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <TagChip key={t.slug} tag={t} />
      ))}
    </div>
  )
}
