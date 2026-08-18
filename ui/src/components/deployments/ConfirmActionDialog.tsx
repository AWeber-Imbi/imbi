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
  /** Extra body content between the description and the footer. */
  children?: ReactNode
  /** Holds the confirm button, e.g. until a CI failure is acknowledged. */
  confirmDisabled?: boolean
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
  children,
  confirmDisabled = false,
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
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction disabled={confirmDisabled} onClick={onConfirm}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
