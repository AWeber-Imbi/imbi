import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useSavedFlash } from '@/hooks/useSavedFlash'

export interface UseEditableKeyValueMapOptions<V> {
  /**
   * Treat a value as "empty" for the purposes of the blur-delete flow.
   * Strings default to `trim() === ''`. Non-string shapes must supply this
   * or set `confirmEmptyDelete: false`.
   */
  isEmpty?: (value: V) => boolean
  /**
   * Optional value normalization applied to `serverMap` before it becomes
   * drafts. Useful when the server can return heterogeneous shapes
   * (e.g. string | number for identifiers).
   */
  normalize?: (raw: Record<string, V>) => Record<string, V>
  /**
   * Trim/normalize an individual value before comparing and patching. For
   * strings this is typically `.trim()`; omit for non-string values.
   */
  normalizeValue?: (value: V) => V
  /**
   * Persist a full key→value map. The hook never calls this with a partial
   * payload; callers that need to strip empties should pass `transformPatch`.
   */
  onPatch: (payload: Record<string, V>) => Promise<void>
  /**
   * Raw server-supplied map. The hook normalizes it and uses it both as the
   * baseline for patches and as the source that drafts resync from.
   */
  serverMap: Record<string, V>
  /**
   * Optional transform applied to the merged payload immediately before it
   * is sent to `onPatch`. Links use this to drop empty-string entries so
   * they aren't persisted alongside real values.
   */
  transformPatch?: (payload: Record<string, V>) => Record<string, V>
}

export interface UseEditableKeyValueMapResult<V> {
  cancelDelete: () => void
  confirmDelete: () => Promise<void>
  drafts: Record<string, V>
  /** Fire the per-key "saved ✓" indicator manually (e.g., from a bespoke blur). */
  flash: (key: string) => void
  handleBlur: (key: string) => Promise<void>
  handleNewBlur: () => Promise<void>
  newKey: null | string
  newValue: null | V
  /** Attach to the new-value input so it focuses after a key is picked. */
  newValueRef: React.RefObject<HTMLInputElement | null>
  pendingDelete: null | string
  requestDelete: (key: string) => void
  saved: Record<string, boolean>
  /** Bump this on the Select's `key` prop to force remount after an add. */
  selectKey: number
  setDraft: (key: string, value: V) => void
  setNewKey: (key: string) => void
  setNewValue: (value: V) => void
}

/**
 * Shared state + handlers for the "editable key → value map" pattern used by
 * the project Overview cards (identifiers, links, …). Handles optimistic
 * drafts, per-key saved flash, delete confirmation, and the "add new" row
 * with auto-focus and select-reset.
 *
 * Concurrency: blur payloads always merge the latest `drafts` on top of
 * `serverMap` so a blur racing an in-flight PATCH does not revive stale
 * server values for other fields the user is also editing.
 */
export function useEditableKeyValueMap<V>(
  options: UseEditableKeyValueMapOptions<V>,
): UseEditableKeyValueMapResult<V> {
  const {
    isEmpty = defaultIsEmpty,
    normalize,
    normalizeValue = identity,
    onPatch,
    serverMap: rawServerMap,
    transformPatch = identity,
  } = options

  const serverMap = useMemo(
    () => (normalize ? normalize(rawServerMap) : rawServerMap),
    [rawServerMap, normalize],
  )

  const [drafts, setDrafts] = useState<Record<string, V>>(serverMap)
  const [pendingDelete, setPendingDelete] = useState<null | string>(null)
  const [newKey, setNewKeyState] = useState<null | string>(null)
  const [newValue, setNewValueState] = useState<null | V>(null)
  const [selectKey, setSelectKey] = useState(0)
  const newValueRef = useRef<HTMLInputElement>(null)
  const shouldFocusNewValue = useRef(false)
  const { flash, saved } = useSavedFlash()

  useEffect(() => {
    setDrafts(serverMap)
  }, [serverMap])

  useEffect(() => {
    if (shouldFocusNewValue.current) {
      newValueRef.current?.focus()
      shouldFocusNewValue.current = false
    }
  })

  const setDraft = useCallback((key: string, value: V) => {
    setDrafts((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleBlur = useCallback(
    async (key: string) => {
      const raw = drafts[key]
      const next = raw === undefined ? raw : normalizeValue(raw)
      const current = serverMap[key]
      if (next === current) return
      if (
        next !== undefined &&
        isEmpty(next) &&
        current !== undefined &&
        !isEmpty(current)
      ) {
        setPendingDelete(key)
        return
      }
      // Merge the latest drafts so a blur that races with an in-flight PATCH
      // does not revive stale server values for concurrently-edited fields.
      const merged: Record<string, V> = {
        ...serverMap,
        ...drafts,
        ...(next !== undefined ? { [key]: next } : {}),
      }
      try {
        await onPatch(transformPatch(merged))
        flash(key)
      } catch {
        // Parent surfaces the error; keep the draft for retry.
      }
    },
    [
      drafts,
      serverMap,
      onPatch,
      normalizeValue,
      isEmpty,
      transformPatch,
      flash,
    ],
  )

  const requestDelete = useCallback(
    (key: string) => {
      const current = serverMap[key]
      if (current === undefined || isEmpty(current)) return
      setPendingDelete(key)
    },
    [serverMap, isEmpty],
  )

  const cancelDelete = useCallback(() => {
    const key = pendingDelete
    // Only restore the draft when it looks like the user emptied the input
    // (the case that triggered the delete dialog on blur). When delete was
    // requested via a button with a non-empty draft, preserve in-progress edits.
    if (
      key &&
      serverMap[key] !== undefined &&
      !isEmpty(serverMap[key]) &&
      (drafts[key] === undefined || isEmpty(drafts[key]))
    ) {
      setDrafts((prev) => ({ ...prev, [key]: serverMap[key] }))
    }
    setPendingDelete(null)
  }, [pendingDelete, serverMap, drafts, isEmpty])

  const confirmDelete = useCallback(async () => {
    const key = pendingDelete
    if (!key) return
    // Merge drafts on top of the server baseline so unsaved edits to *other*
    // keys aren't clobbered when we patch the delete. Then omit the deleted
    // key from the payload.
    const merged: Record<string, V> = { ...serverMap, ...drafts }
    const payload: Record<string, V> = {}
    for (const [k, v] of Object.entries(merged)) {
      if (k === key) continue
      payload[k] = v
    }
    try {
      await onPatch(transformPatch(payload))
      setDrafts((prev) => {
        const { [key]: _removed, ...rest } = prev
        return rest
      })
    } catch {
      // Parent surfaces the error.
    } finally {
      setPendingDelete(null)
    }
  }, [pendingDelete, serverMap, drafts, onPatch, transformPatch])

  const setNewKey = useCallback((key: string) => {
    if (!key) return
    setNewKeyState(key)
    shouldFocusNewValue.current = true
  }, [])

  const setNewValue = useCallback((value: V) => {
    setNewValueState(value)
  }, [])

  const handleNewBlur = useCallback(async () => {
    if (!newKey || newValue === null) return
    const normalized = normalizeValue(newValue)
    if (isEmpty(normalized)) return
    // Include the latest drafts so concurrent edits to existing entries
    // aren't reverted to stale server values by this add.
    const merged: Record<string, V> = {
      ...serverMap,
      ...drafts,
      [newKey]: normalized,
    }
    try {
      await onPatch(transformPatch(merged))
      flash(newKey)
      setNewKeyState(null)
      setNewValueState(null)
      setSelectKey((k) => k + 1)
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }, [
    newKey,
    newValue,
    serverMap,
    drafts,
    onPatch,
    normalizeValue,
    isEmpty,
    transformPatch,
    flash,
  ])

  return {
    cancelDelete,
    confirmDelete,
    drafts,
    flash,
    handleBlur,
    handleNewBlur,
    newKey,
    newValue,
    newValueRef,
    pendingDelete,
    requestDelete,
    saved,
    selectKey,
    setDraft,
    setNewKey,
    setNewValue,
  }
}

function defaultIsEmpty<V>(value: V): boolean {
  if (value == null) return true
  if (typeof value === 'string') return value.trim() === ''
  return false
}

function identity<T>(x: T): T {
  return x
}
