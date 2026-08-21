import { Tag } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

/**
 * Version badge for a commit a tag points directly at — most commits
 * are not tagged and render nothing. Amber like the tagged-release
 * accents elsewhere, mono like the sha it annotates.
 */
export function TagBadge({ tag }: { tag: null | string | undefined }) {
  if (!tag) return null
  return (
    <Badge
      className="inline-flex shrink-0 items-center gap-1 font-mono"
      variant="warning"
    >
      <Tag className="size-3" />
      {tag}
    </Badge>
  )
}
