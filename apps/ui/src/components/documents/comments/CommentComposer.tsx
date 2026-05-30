import type { KeyboardEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface Props {
  autoFocus?: boolean
  busy?: boolean
  initial?: string
  onCancel?: () => void
  onSubmit: (body: string) => void
  placeholder?: string
  submitLabel?: string
}

const MAX_HEIGHT = 220

/**
 * Plain-text comment composer. Cmd/Ctrl-Enter submits, Escape cancels (when a
 * cancel handler is supplied), and the textarea auto-grows up to a max height.
 * No @mention autocomplete in Phase 1 — that lands in Phase 3.
 */
export function CommentComposer({
  autoFocus = false,
  busy = false,
  initial = '',
  onCancel,
  onSubmit,
  placeholder = 'Add a comment…',
  submitLabel = 'Comment',
}: Props) {
  const [text, setText] = useState(initial)
  const ref = useRef<HTMLTextAreaElement>(null)

  const grow = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }

  useEffect(() => {
    const el = ref.current
    if (!el) return
    grow(el)
    if (autoFocus) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  }, [autoFocus])

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    onSubmit(trimmed)
    setText('')
    if (ref.current) ref.current.style.height = 'auto'
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const action = keyAction(e)
    if (!action) return
    e.preventDefault()
    if (action === 'submit') submit()
    else onCancel?.()
  }

  const empty = !text.trim()

  return (
    <div className="flex flex-col gap-1.5">
      <Textarea
        className="min-h-9 resize-none text-[13.5px]"
        onChange={(e) => {
          setText(e.target.value)
          grow(e.target)
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        ref={ref}
        rows={1}
        value={text}
      />
      <div className="flex items-center justify-between">
        <span className="text-tertiary text-[11px]">
          {empty ? '' : 'Cmd + Enter to send'}
        </span>
        <div className="flex items-center gap-2">
          {onCancel && (
            <Button onClick={onCancel} size="sm" type="button" variant="ghost">
              Cancel
            </Button>
          )}
          <Button
            disabled={empty || busy}
            onClick={submit}
            size="sm"
            type="button"
          >
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Map a keydown to a composer action: Cmd/Ctrl-Enter submits, Escape cancels. */
// fallow-ignore-next-line complexity
function keyAction(
  e: KeyboardEvent<HTMLTextAreaElement>,
): 'cancel' | 'submit' | null {
  if (e.key === 'Escape') return 'cancel'
  const submitChord = e.key === 'Enter' && (e.metaKey || e.ctrlKey)
  return submitChord ? 'submit' : null
}
