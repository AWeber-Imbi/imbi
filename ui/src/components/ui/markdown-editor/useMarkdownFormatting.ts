import type { KeyboardEvent, RefObject } from 'react'
import { useCallback, useLayoutEffect, useRef } from 'react'

import type { MarkdownFormat } from '@/lib/markdown-format'
import { applyMarkdownFormat, spliceEdit } from '@/lib/markdown-format'

/** Cmd (Mac) / Ctrl (elsewhere) + key → format. */
const SHORTCUTS: Record<string, MarkdownFormat> = {
  b: 'bold',
  i: 'italic',
  k: 'link',
}

/**
 * Applies toolbar formats to a markdown textarea.
 *
 * Edits go through `execCommand('insertText')` so they land in the browser's
 * native undo stack (Cmd-Z undoes a toolbar click like typed text) and fire
 * the textarea's normal onChange. Where `execCommand` is unavailable (jsdom,
 * very old browsers) it falls back to `onChange(nextValue)` and restores the
 * selection once React has re-rendered with the new value.
 */
export function useMarkdownFormatting(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  onChange: (value: string) => void,
) {
  const pendingSelection = useRef<[number, number] | null>(null)

  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el || !pendingSelection.current) return
    el.setSelectionRange(...pendingSelection.current)
    pendingSelection.current = null
  })

  const format = useCallback(
    (action: MarkdownFormat) => {
      const el = textareaRef.current
      if (!el || el.disabled || el.readOnly) return
      const edit = applyMarkdownFormat(action, {
        selectionEnd: el.selectionEnd,
        selectionStart: el.selectionStart,
        value: el.value,
      })
      el.focus()
      el.setSelectionRange(edit.replaceStart, edit.replaceEnd)
      const inserted =
        typeof document.execCommand === 'function' &&
        (edit.text
          ? document.execCommand('insertText', false, edit.text)
          : document.execCommand('delete', false))
      if (inserted) {
        el.setSelectionRange(edit.selectionStart, edit.selectionEnd)
      } else {
        pendingSelection.current = [edit.selectionStart, edit.selectionEnd]
        onChange(spliceEdit(el.value, edit))
      }
    },
    [onChange, textareaRef],
  )

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return
      const action = SHORTCUTS[e.key.toLowerCase()]
      if (!action) return
      e.preventDefault()
      format(action)
    },
    [format],
  )

  return { format, onKeyDown }
}
