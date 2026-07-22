import type { ReactNode } from 'react'

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

interface ConfirmActionDialogProps {
  confirmLabel: string
  description: ReactNode
  onCancel: () => void
  onConfirm: () => void
  open: boolean
  title: string
}

/**
 * Non-destructive confirm for one-click dispatch rows (deploy / roll
 * back). The shared ConfirmDialog hard-codes destructive styling, so the
 * deployments tab keeps its own default-styled variant.
 */
export function ConfirmActionDialog({
  confirmLabel,
  description,
  onCancel,
  onConfirm,
  open,
  title,
}: ConfirmActionDialogProps) {
  return (
    <AlertDialog
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
      open={open}
    >
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
