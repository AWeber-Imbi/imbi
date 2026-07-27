import { useEffect, useState } from 'react'

import { Ban } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import { Textarea } from '@/components/ui/textarea'

interface BlockReleaseDialogProps {
  isPending: boolean
  onBlock: (reason: string) => void
  onOpenChange: (open: boolean) => void
  open: boolean
  tag: string
}

/**
 * Captures the reason a release is being blocked. The reason is required —
 * the block is what stops a deploy, so whoever hits the 409 needs to know
 * why without going to ask.
 */
export function BlockReleaseDialog({
  isPending,
  onBlock,
  onOpenChange,
  open,
  tag,
}: BlockReleaseDialogProps) {
  const [reason, setReason] = useState('')

  // Clear the draft between openings so a reason typed for one release
  // can't be submitted against another.
  useEffect(() => {
    if (open) setReason('')
  }, [open, tag])

  const trimmed = reason.trim()
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="text-danger size-4" />
            Block release {tag}
          </DialogTitle>
          <DialogDescription>
            Deploys and promotes of <span className="font-mono">{tag}</span>{' '}
            will be refused until it is unblocked. Environments already running
            it are left alone.
          </DialogDescription>
        </DialogHeader>
        <div className="p-6">
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>
              Reason
              <RequiredAsterisk />
            </span>
            <Textarea
              autoFocus
              className="min-h-24 text-sm"
              onChange={(e) => setReason(e.target.value)}
              placeholder="Rolled back — regression in the checkout flow"
              value={reason}
            />
          </Label>
        </div>
        <DialogFooter>
          <Button
            onClick={() => onOpenChange(false)}
            type="button"
            variant="ghost"
          >
            Cancel
          </Button>
          <Button
            disabled={!trimmed || isPending}
            onClick={() => onBlock(trimmed)}
            type="button"
          >
            Block {tag}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
