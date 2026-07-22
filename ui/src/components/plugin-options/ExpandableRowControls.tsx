import { ChevronDown, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

// Chevron + override-count badge shown in the trailing toggle cell of
// the expandable plugin-override tables. Shared between the admin
// service-plugin and project-plugin tables so the cell looks the same
// in both places and the JSX-clone audit stays clean.
export function OverrideCountChevron({
  count,
  isExpanded,
}: {
  count: number
  isExpanded: boolean
}) {
  return (
    <span className="relative inline-flex items-center">
      <ChevronDown
        className={`text-tertiary size-3.5 transition-transform ${
          isExpanded ? 'rotate-180' : ''
        }`}
      />
      {count > 0 && (
        <Badge className="ml-1 h-4 px-1 text-[10px]" variant="secondary">
          {count}
        </Badge>
      )}
    </span>
  )
}

// Trash-icon "remove row" button that stops click propagation so the
// row's expand toggle doesn't fire when the user removes the row.
export function RemoveRowButton({
  ariaLabel,
  onRemove,
}: {
  ariaLabel: string
  onRemove: () => void
}) {
  return (
    <Button
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation()
        onRemove()
      }}
      size="icon"
      variant="ghost"
    >
      <Trash2 className="text-destructive size-3" />
    </Button>
  )
}
