import { useCallback, useEffect, useState } from 'react'

export interface UseInlineEditOptions<T> {
  /** Compare draft and initial. Defaults to `Object.is`. */
  equals?: (a: T, b: T) => boolean
  initial: T
  onCommit: (value: T) => Promise<void> | void
}

export interface UseInlineEditResult<T> {
  cancel: () => void
  commit: () => Promise<void>
  draft: T
  enter: () => void
  error: null | string
  handleBlur: (e: React.FocusEvent) => Promise<void> | void
  handleKeyDown: (e: React.KeyboardEvent) => Promise<void> | void
  isEditing: boolean
  setDraft: (v: T) => void
  setError: (s: null | string) => void
}

export function useInlineEdit<T>(
  opts: UseInlineEditOptions<T>,
): UseInlineEditResult<T> {
  const equals = opts.equals ?? Object.is
  const { initial, onCommit } = opts
  const [isEditing, setEditing] = useState(false)
  const [draft, setDraft] = useState<T>(initial)
  const [error, setError] = useState<null | string>(null)

  // Keep draft in sync with external value when not editing.
  useEffect(() => {
    if (!isEditing) setDraft(initial)
  }, [initial, isEditing])

  const enter = useCallback(() => {
    setDraft(initial)
    setError(null)
    setEditing(true)
  }, [initial])

  const cancel = useCallback(() => {
    setDraft(initial)
    setError(null)
    setEditing(false)
  }, [initial])

  const commit = useCallback(async () => {
    if (equals(draft, initial)) {
      setEditing(false)
      return
    }
    try {
      await onCommit(draft)
      setError(null)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [draft, initial, onCommit, equals])

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
    if (equals(draft, initial)) {
      setEditing(false)
      return
    }
    await commit()
  }, [draft, initial, equals, commit])

  return {
    cancel,
    commit,
    draft,
    enter,
    error,
    handleBlur,
    handleKeyDown,
    isEditing,
    setDraft,
    setError,
  }
}
