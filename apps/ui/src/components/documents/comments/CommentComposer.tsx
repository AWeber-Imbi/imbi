import type { KeyboardEvent } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Gravatar } from '@/components/ui/gravatar'
import { Textarea } from '@/components/ui/textarea'

import type { MentionCandidate } from './mentions'
import { resolveMentions } from './mentions'
import { useMentionAutocomplete } from './useMentionAutocomplete'

interface Props {
  autoFocus?: boolean
  busy?: boolean
  /** Email → display_name, used both for @mention autocomplete and resolution. */
  displayNames?: Map<string, string>
  initial?: string
  onCancel?: () => void
  onSubmit: (body: string, mentions: string[]) => void
  placeholder?: string
  submitLabel?: string
}

const MAX_HEIGHT = 220

/** Keys the open mention popover consumes; refresh must not undo their effect. */
const POPOVER_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', 'Escape', 'Tab'])

/**
 * Plain-text comment composer with @mention autocomplete. Typing `@` opens a
 * popover of users (filtered by name/email); ↑/↓ navigate, Enter/Tab select,
 * Esc closes it. Cmd/Ctrl-Enter submits and the textarea auto-grows up to a max
 * height. Mentioned display names are resolved to emails (against
 * `displayNames`) and handed to `onSubmit` alongside the body text. The mention
 * state machine lives in `useMentionAutocomplete`.
 */
// fallow-ignore-next-line complexity
export function CommentComposer({
  autoFocus = false,
  busy = false,
  displayNames,
  initial = '',
  onCancel,
  onSubmit,
  placeholder = 'Add a comment…',
  submitLabel = 'Comment',
}: Props) {
  const [text, setText] = useState(initial)
  const ref = useRef<HTMLTextAreaElement>(null)

  const candidates = useMemo<MentionCandidate[]>(() => {
    if (!displayNames) return []
    return [...displayNames].map(([email, display_name]) => ({
      display_name,
      email,
    }))
  }, [displayNames])

  const grow = () => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }

  // Set the value and (optionally) restore the caret + grow on the next frame.
  const setValue = (next: string, caret?: number) => {
    setText(next)
    requestAnimationFrame(() => {
      const el = ref.current
      if (!el) return
      if (caret !== undefined) {
        el.focus()
        el.setSelectionRange(caret, caret)
      }
      grow()
    })
  }

  const mentions = useMentionAutocomplete(ref, candidates, text, setValue)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    grow()
    if (autoFocus) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  }, [autoFocus])

  // fallow-ignore-next-line complexity
  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    onSubmit(trimmed, resolveMentions(trimmed, displayNames ?? new Map()))
    setText('')
    mentions.close()
    if (ref.current) ref.current.style.height = 'auto'
  }

  // fallow-ignore-next-line complexity
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentions.onKeyDown(e)) return
    if (e.key === 'Escape') {
      onCancel?.()
      return
    }
    if (isSubmitChord(e)) {
      e.preventDefault()
      submit()
    }
  }

  const empty = !text.trim()

  return (
    <div className="relative flex flex-col gap-1.5">
      <Textarea
        className="min-h-9 resize-none text-[13.5px]"
        onChange={(e) => {
          setText(e.target.value)
          grow()
          mentions.refresh(e.target)
        }}
        onKeyDown={onKeyDown}
        onKeyUp={(e) => {
          // Don't undo the navigation/selection/dismiss the popover just did.
          if (mentions.open && POPOVER_KEYS.has(e.key)) return
          mentions.refresh(e.currentTarget)
        }}
        placeholder={placeholder}
        ref={ref}
        rows={1}
        value={text}
      />
      {mentions.open && (
        <MentionPopover
          active={mentions.active}
          matches={mentions.matches}
          onPick={mentions.pick}
        />
      )}
      <div className="flex items-center justify-between">
        <span className="text-tertiary text-[11px]">
          {empty ? '' : 'Cmd + Enter to send · @ to mention'}
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

/** Cmd/Ctrl-Enter submits the composer. */
function isSubmitChord(e: KeyboardEvent<HTMLTextAreaElement>): boolean {
  return e.key === 'Enter' && (e.metaKey || e.ctrlKey)
}

function MentionPopover({
  active,
  matches,
  onPick,
}: {
  active: number
  matches: MentionCandidate[]
  onPick: (candidate: MentionCandidate) => void
}) {
  return (
    <div className="border-tertiary bg-primary absolute top-9 left-0 z-20 flex w-64 flex-col gap-0.5 rounded-md border p-1 shadow-md">
      {matches.map((candidate, i) => (
        <button
          className={
            i === active
              ? 'bg-secondary flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px]'
              : 'hover:bg-secondary flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px]'
          }
          key={candidate.email}
          onMouseDown={(e) => {
            e.preventDefault()
            onPick(candidate)
          }}
          type="button"
        >
          <Gravatar
            className="shrink-0 rounded-full"
            email={candidate.email}
            size={18}
          />
          <span className="text-primary truncate">
            {candidate.display_name}
          </span>
        </button>
      ))}
    </div>
  )
}
