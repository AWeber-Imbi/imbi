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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { BlockerType } from '@/types'

interface AddBlockerDialogProps {
  isPending: boolean
  onBlock: (type: BlockerType, description: string) => void
  onOpenChange: (open: boolean) => void
  open: boolean
  tag: string
}

/** Type labels, in the order they are offered. */
export const BLOCKER_TYPES: { label: string; value: BlockerType }[] = [
  { label: 'Manual', value: 'manual' },
  { label: 'Product review', value: 'product-review' },
  { label: 'QA', value: 'qa' },
  { label: 'Deployment order', value: 'deploy-order' },
  { label: 'Dependency', value: 'dependency' },
  { label: 'Build failure', value: 'build-failure' },
  { label: 'Drift', value: 'drift' },
]

/**
 * Captures what is holding a release up. The description is required —
 * the blocker is what stops a deploy, so whoever hits the 409 needs to
 * know why without going to ask.
 */
export function AddBlockerDialog({
  isPending,
  onBlock,
  onOpenChange,
  open,
  tag,
}: AddBlockerDialogProps) {
  const [description, setDescription] = useState('')
  const [type, setType] = useState<BlockerType>('manual')

  // Clear the draft between openings so a reason typed for one release
  // can't be submitted against another.
  useEffect(() => {
    if (open) {
      setDescription('')
      setType('manual')
    }
  }, [open, tag])

  const trimmed = description.trim()
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="text-danger size-4" />
            Add blocker to {tag}
          </DialogTitle>
          <DialogDescription>
            Deploys and promotes of <span className="font-mono">{tag}</span>{' '}
            will be refused until every blocker on it is resolved. Environments
            already running it are left alone.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>Type</span>
            <Select
              onValueChange={(next) => setType(next as BlockerType)}
              value={type}
            >
              <SelectTrigger className="text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BLOCKER_TYPES.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Label>
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>
              Reason
              <RequiredAsterisk />
            </span>
            <Textarea
              autoFocus
              className="min-h-24 text-sm"
              maxLength={500}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Rolled back — regression in the checkout flow"
              value={description}
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
            onClick={() => onBlock(type, trimmed)}
            type="button"
          >
            Add blocker
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
