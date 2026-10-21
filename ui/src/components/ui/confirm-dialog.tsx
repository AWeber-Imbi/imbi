import { useRef } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog'
import { buttonVariants } from './button'

interface ConfirmDialogProps {
  confirmLabel?: string
  description?: string
  onCancel: () => void
  onConfirm: () => void
  open: boolean
  title: string
}

export function ConfirmDialog({
  confirmLabel = 'Delete',
  description = 'This action cannot be undone.',
  onCancel,
  onConfirm,
  open,
  title,
}: ConfirmDialogProps) {
  // The dialog has no Radix trigger, so Radix cannot return focus on
  // close. Keep the element that had focus on open and focus it again.
  const opener = useRef<HTMLElement | null>(null)
  return (
    <AlertDialog
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
      open={open}
    >
      <AlertDialogContent
        className="sm:max-w-md"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          opener.current?.focus()
        }}
        onOpenAutoFocus={() => {
          opener.current = document.activeElement as HTMLElement | null
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && (
            <AlertDialogDescription>{description}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={buttonVariants({ variant: 'destructive' })}
            onClick={onConfirm}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
