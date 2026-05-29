import { useEffect, useState } from 'react'

import { ArrowRight } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Checkbox } from '@/components/ui/checkbox'
import type { LifecyclePreviewEntry } from '@/types'

interface RelocatePreviewDialogProps {
  // Only the entries with ``would_relocate === true`` — the caller filters.
  entries: LifecyclePreviewEntry[]
  onCancel: () => void
  // ``transfer`` reflects the opt-in checkbox: ``true`` dispatches the
  // relocate (moves the backing remote), ``false`` is a metadata-only
  // type change.
  onConfirm: (transfer: boolean) => void
  open: boolean
  pending?: boolean
}

const targetLabel = (target: LifecyclePreviewEntry['current_target']): string =>
  target?.display ?? target?.identifier ?? '—'

export function RelocatePreviewDialog({
  entries,
  onCancel,
  onConfirm,
  open,
  pending = false,
}: RelocatePreviewDialogProps) {
  // Default unchecked: the backend's ``transfer_repository`` defaults to
  // false ("a type change alone never moves the remote"), so confirming
  // without opting in is a safe metadata-only change.
  const [transfer, setTransfer] = useState(false)

  useEffect(() => {
    if (open) setTransfer(false)
  }, [open])

  return (
    <AlertDialog
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
      open={open}
    >
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Move the backing repository?</AlertDialogTitle>
          <AlertDialogDescription>
            This project-type change would route the following to a new
            location. The type change is saved either way — checking the box
            also moves the remote.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <ul className="border-tertiary space-y-2 border-y py-3">
          {entries.map((entry) => (
            <li className="text-sm" key={entry.plugin_id}>
              <span className="text-tertiary">{entry.plugin_slug}</span>
              <div className="text-primary mt-0.5 flex items-center gap-2 font-mono text-xs">
                <span>{targetLabel(entry.current_target)}</span>
                <ArrowRight aria-hidden className="text-tertiary size-3.5" />
                <span>{targetLabel(entry.next_target)}</span>
              </div>
            </li>
          ))}
        </ul>

        <label className="text-secondary flex items-center gap-2 text-sm">
          <Checkbox
            checked={transfer}
            disabled={pending}
            onCheckedChange={(checked) => setTransfer(checked === true)}
          />
          <span>Also move the repository to the new location.</span>
        </label>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={() => onConfirm(transfer)}
          >
            {pending ? 'Saving…' : 'Save changes'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
