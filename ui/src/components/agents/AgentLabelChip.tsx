import type { ReactNode } from 'react'

import { LabelChip } from '@/components/ui/label-chip'

interface ChipTag {
  color?: null | string
  name: string
  slug: string
}

/** A tag as a label chip in the tag color, or neutral with no color. */
export function AgentLabelChip({
  children,
  tag,
}: {
  children?: ReactNode
  tag: ChipTag
}) {
  return (
    <LabelChip
      className={tag.color ? undefined : 'border-tertiary text-secondary'}
      hex={tag.color ?? ''}
    >
      {tag.name}
      {children}
    </LabelChip>
  )
}

export function AgentLabels({ tags }: { tags: ChipTag[] }) {
  if (tags.length === 0) return <span className="text-tertiary text-sm">—</span>
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <AgentLabelChip key={t.slug} tag={t} />
      ))}
    </div>
  )
}
