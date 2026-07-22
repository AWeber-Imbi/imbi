import { useCallback, useEffect, useState } from 'react'

import type { CommentAnchor, CommentThread } from '@/types/comments'

import { anchorFromSelection } from './anchor'
import {
  applyHighlights,
  clearHighlightState,
  markHighlight,
} from './highlight'
import type { SelectionRect } from './SelectionToolbar'

interface Draft {
  anchor: CommentAnchor
  id: string
}

interface InlineCommentsApi {
  bump: () => void
  draft: Draft | null
  focusedId: null | string
  layoutTick: number
  onCancelDraft: () => void
  onConfirmedDraft: () => void
  onStartDraft: () => void
  orphanedIds: Set<string>
  selectionRect: null | SelectionRect
  setFocusedId: (id: null | string) => void
  setHoverId: (id: null | string) => void
}

interface Options {
  articleRef: React.RefObject<HTMLElement | null>
  content: string
  enabled: boolean
  inlineThreads: CommentThread[]
}

const SELECTION_DEBOUNCE = 10

/**
 * Orchestrates inline-comment DOM concerns for the reader: selection→toolbar,
 * the highlight overlay (re-applied on content/thread changes), focus/hover
 * highlight syncing, a pending draft anchor, and a layout tick that fires on
 * scroll/resize so the margin bar re-measures. The markdown source is never
 * mutated — `applyHighlights` clears and re-wraps on every run.
 */
export function useInlineComments({
  articleRef,
  content,
  enabled,
  inlineThreads,
}: Options): InlineCommentsApi {
  const [focusedId, setFocusedId] = useState<null | string>(null)
  const [hoverId, setHoverId] = useState<null | string>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [selectionRect, setSelectionRect] = useState<null | SelectionRect>(null)
  const [orphanedIds, setOrphanedIds] = useState<Set<string>>(new Set())
  const [layoutTick, setLayoutTick] = useState(0)

  const bump = useCallback(() => setLayoutTick((t) => t + 1), [])

  // Re-apply the highlight overlay whenever the article content or the set of
  // inline threads changes. Compute which threads are orphaned (quote not found).
  const threadSig = inlineThreads
    .map((t) => `${t.id}:${t.resolved ? 'r' : 'o'}`)
    .join(',')
  useEffect(() => {
    const article = articleRef.current
    if (!article) return
    if (!enabled) {
      applyHighlights(article, [])
      setOrphanedIds(new Set())
      return
    }
    const anchored = applyHighlights(article, inlineThreads)
    setOrphanedIds(
      new Set(
        inlineThreads
          .filter((t) => t.anchor && !anchored.has(t.id))
          .map((t) => t.id),
      ),
    )
    bump()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleRef, content, threadSig, enabled, bump])

  // Sync focus/hover visual state onto the highlight spans.
  // fallow-ignore-next-line complexity
  useEffect(() => {
    const article = articleRef.current
    if (!article) return
    clearHighlightState(article)
    if (focusedId)
      markHighlight(article, focusedId, { focused: true, hovered: false })
    if (hoverId && hoverId !== focusedId)
      markHighlight(article, hoverId, { focused: false, hovered: true })
  }, [articleRef, focusedId, hoverId, layoutTick])

  // Selection → floating toolbar.
  // fallow-ignore-next-line complexity
  useEffect(() => {
    if (!enabled) return
    const onMouseUp = () => {
      setTimeout(() => {
        setSelectionRect(selectionToolbarRect(articleRef.current))
      }, SELECTION_DEBOUNCE)
    }
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('[data-selection-toolbar]')) setSelectionRect(null)
    }
    document.addEventListener('mouseup', onMouseUp)
    document.addEventListener('mousedown', onMouseDown)
    return () => {
      document.removeEventListener('mouseup', onMouseUp)
      document.removeEventListener('mousedown', onMouseDown)
    }
  }, [articleRef, enabled])

  // Click a highlight → focus its card; click elsewhere in the article → unfocus.
  useEffect(() => {
    if (!enabled) return
    const article = articleRef.current
    if (!article) return
    const onClick = (e: MouseEvent) => {
      const id = clickedThreadId(e.target)
      if (id) setFocusedId(id)
      else if (!draft) setFocusedId(null)
    }
    article.addEventListener('click', onClick)
    return () => article.removeEventListener('click', onClick)
  }, [articleRef, enabled, draft])

  // Esc unfocuses (and cancels a draft).
  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setFocusedId(null)
      setDraft(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [enabled])

  // Recompute card positions on scroll/resize.
  useEffect(() => {
    if (!enabled) return
    const onChange = () => bump()
    window.addEventListener('scroll', onChange, { passive: true })
    window.addEventListener('resize', onChange)
    return () => {
      window.removeEventListener('scroll', onChange)
      window.removeEventListener('resize', onChange)
    }
  }, [enabled, bump])

  const onStartDraft = useCallback(() => {
    const article = articleRef.current
    if (!article) return
    const anchor = anchorFromSelection(article)
    if (!anchor) {
      setSelectionRect(null)
      return
    }
    const id = `draft-${Date.now()}`
    setDraft({ anchor, id })
    setFocusedId(id)
    setSelectionRect(null)
    const sel = window.getSelection()
    if (sel) sel.removeAllRanges()
    bump()
  }, [articleRef, bump])

  const onCancelDraft = useCallback(() => {
    setDraft(null)
    setFocusedId(null)
  }, [])

  const onConfirmedDraft = useCallback(() => {
    setDraft(null)
    setFocusedId(null)
  }, [])

  return {
    bump,
    draft,
    focusedId,
    layoutTick,
    onCancelDraft,
    onConfirmedDraft,
    onStartDraft,
    orphanedIds,
    selectionRect,
    setFocusedId,
    setHoverId,
  }
}

/** The thread id of a clicked highlight span, or null when none was hit. */
function clickedThreadId(target: EventTarget | null): null | string {
  const span = (target as HTMLElement).closest?.('.comment-highlight')
  return span?.getAttribute('data-thread-id') ?? null
}

/** Compute the floating-toolbar rect for the current selection, or null. */
// fallow-ignore-next-line complexity
function selectionToolbarRect(
  article: HTMLElement | null,
): null | SelectionRect {
  const sel = window.getSelection()
  if (!article || !sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const range = sel.getRangeAt(0)
  if (
    !article.contains(range.commonAncestorContainer) ||
    !range.toString().trim()
  ) {
    return null
  }
  const r = range.getBoundingClientRect()
  return { bottom: r.bottom, left: r.left + r.width / 2, top: r.top }
}
