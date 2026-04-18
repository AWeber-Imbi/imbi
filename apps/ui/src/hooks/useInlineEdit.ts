import { useCallback, useEffect, useState } from 'react'

export interface UseInlineEditOptions<T> {
  initial: T
  onCommit: (value: T) => Promise<void> | void
  /** Compare draft and initial. Defaults to `Object.is`. */
  equals?: (a: T, b: T) => boolean
}

export interface UseInlineEditResult<T> {
  isEditing: boolean
  enter: () => void
  cancel: () => void
  commit: () => Promise<void>
  draft: T
  setDraft: (v: T) => void
  handleKeyDown: (e: React.KeyboardEvent) => void | Promise<void>
  handleBlur: (e: React.FocusEvent) => void | Promise<void>
  error: string | null
  setError: (s: string | null) => void
}

export function useInlineEdit<T>(
  opts: UseInlineEditOptions<T>,
): UseInlineEditResult<T> {
  const equals = opts.equals ?? Object.is
  const [isEditing, setEditing] = useState(false)
  const [draft, setDraft] = useState<T>(opts.initial)
  const [error, setError] = useState<string | null>(null)

  // Keep draft in sync with external value when not editing.
  useEffect(() => {
    if (!isEditing) setDraft(opts.initial)
  }, [opts.initial, isEditing])

  const enter = useCallback(() => {
    setDraft(opts.initial)
    setError(null)
    setEditing(true)
  }, [opts.initial])

  const cancel = useCallback(() => {
    setDraft(opts.initial)
    setError(null)
    setEditing(false)
  }, [opts.initial])

  const commit = useCallback(async () => {
    if (equals(draft, opts.initial)) {
      setEditing(false)
      return
    }
    try {
      await opts.onCommit(draft)
      setError(null)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [draft, opts, equals])

  const handleKeyDown = useCallback(
    async (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        await commit()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        cancel()
      }
    },
    [commit, cancel],
  )

  const handleBlur = useCallback(async () => {
    if (equals(draft, opts.initial)) {
      setEditing(false)
      return
    }
    await commit()
  }, [draft, opts.initial, equals, commit])

  return {
    isEditing,
    enter,
    cancel,
    commit,
    draft,
    setDraft,
    handleKeyDown,
    handleBlur,
    error,
    setError,
  }
}
