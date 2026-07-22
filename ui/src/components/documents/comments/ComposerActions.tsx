import type { KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'

interface Props {
  busy: boolean
  empty: boolean
  /** Hint shown to the left of the buttons while the composer is non-empty. */
  hint: string
  onCancel?: () => void
  onSubmit: () => void
  submitLabel: string
}

/** Shared footer row for comment composers: a hint plus Cancel/submit. */
export function ComposerActions({
  busy,
  empty,
  hint,
  onCancel,
  onSubmit,
  submitLabel,
}: Props) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-tertiary text-[11px]">{empty ? '' : hint}</span>
      <div className="flex items-center gap-2">
        {onCancel && (
          <Button onClick={onCancel} size="sm" type="button" variant="ghost">
            Cancel
          </Button>
        )}
        <Button
          disabled={empty || busy}
          onClick={onSubmit}
          size="sm"
          type="button"
        >
          {submitLabel}
        </Button>
      </div>
    </div>
  )
}

/** Cmd/Ctrl-Enter submits a composer. */
export function isSubmitChord(e: KeyboardEvent<HTMLElement>): boolean {
  return e.key === 'Enter' && (e.metaKey || e.ctrlKey)
}
