import { Button, IconTooltip } from 'imbi-ui'
import { Copy, Trash2 } from 'lucide-react'

// IconTooltip has no `open` prop. Focus opens a Radix tooltip at
// once, so `autoFocus` on the child shows the tooltip in the card.
export const CopyProjectId = () => (
  <div className="flex justify-center p-12">
    <IconTooltip label="Copy project ID">
      <Button aria-label="Copy project ID" autoFocus size="sm" variant="ghost">
        <Copy className="size-4" />
      </Button>
    </IconTooltip>
  </div>
)

export const DeleteSide = () => (
  <div className="flex justify-center p-12">
    <IconTooltip label="Delete environment" side="right">
      <Button
        aria-label="Delete environment"
        autoFocus
        size="sm"
        variant="ghost"
      >
        <Trash2 className="size-4" />
      </Button>
    </IconTooltip>
  </div>
)
