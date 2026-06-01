// Highlight overlay: wrap the text nodes intersecting a resolved Range in
// `<span class="comment-highlight" data-thread-id=…>`, and tear those spans back
// out. Ported from the prototype's domHighlight.jsx wrapRange/unwrapThread.
// The markdown source is never touched — these spans are an overlay re-applied
// (and cleaned up) on every render of the article.

import type { CommentThread } from '@/types/comments'

import { resolveAnchor } from './anchor'

const HIGHLIGHT_CLASS = 'comment-highlight'

/**
 * Apply highlights for the given inline threads to `root`. Always clears first
 * so the overlay is idempotent. Returns the set of thread ids that could be
 * anchored (the complement is "orphaned" and shown in the margin without a
 * highlight).
 */
// fallow-ignore-next-line complexity
export function applyHighlights(
  root: HTMLElement,
  threads: CommentThread[],
): Set<string> {
  clearHighlights(root)
  const anchored = new Set<string>()
  for (const thread of threads) {
    if (!thread.anchor) continue
    const range = resolveAnchor(root, thread.anchor)
    if (!range) continue
    if (wrapRange(range, thread.id, thread.resolved)) anchored.add(thread.id)
  }
  return anchored
}

/** Clear focus/hover classes from every highlight span. */
export function clearHighlightState(root: HTMLElement): void {
  root.querySelectorAll('.' + HIGHLIGHT_CLASS).forEach((span) => {
    span.classList.remove('is-focused', 'is-hover')
  })
}

/** Top of a thread's first highlight relative to `container`, or null. */
export function highlightTop(
  root: HTMLElement,
  container: HTMLElement,
  threadId: string,
): null | number {
  const span = root.querySelector(
    '.' + HIGHLIGHT_CLASS + '[data-thread-id="' + cssEscape(threadId) + '"]',
  )
  if (!span) return null
  return (
    span.getBoundingClientRect().top - container.getBoundingClientRect().top
  )
}

/** Toggle visual state classes on a thread's highlight spans. */
export function markHighlight(
  root: HTMLElement,
  threadId: string,
  state: { focused: boolean; hovered: boolean },
): void {
  root
    .querySelectorAll(
      '.' + HIGHLIGHT_CLASS + '[data-thread-id="' + cssEscape(threadId) + '"]',
    )
    .forEach((span) => {
      span.classList.toggle('is-focused', state.focused)
      span.classList.toggle('is-hover', state.hovered)
    })
}

/** Remove all highlight spans from the root, restoring the original text nodes. */
function clearHighlights(root: HTMLElement): void {
  root.querySelectorAll('.' + HIGHLIGHT_CLASS).forEach((span) => {
    const parent = span.parentNode
    if (!parent) return
    while (span.firstChild) parent.insertBefore(span.firstChild, span)
    parent.removeChild(span)
    parent.normalize()
  })
}

function cssEscape(value: string): string {
  if (window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(value)
  }
  return value.replace(/["\\]/g, '\\$&')
}

/** Collect the text nodes intersecting `range`, in document order. */
function intersectingTextNodes(range: Range): Text[] {
  const root = range.commonAncestorContainer
  const start =
    root.nodeType === Node.TEXT_NODE ? (root.parentNode ?? root) : root
  const walker = document.createTreeWalker(start, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.nodeValue && range.intersectsNode(node)
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT,
  })
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  return nodes
}

/** Wrap the portion of one text node that falls within `range` in a span. */
// fallow-ignore-next-line complexity
function wrapNodeSegment(
  node: Text,
  range: Range,
  threadId: string,
  resolved: boolean,
): boolean {
  const s = node === range.startContainer ? range.startOffset : 0
  const e =
    node === range.endContainer
      ? range.endOffset
      : (node.nodeValue?.length ?? 0)
  if (s >= e) return false
  const seg = document.createRange()
  seg.setStart(node, s)
  seg.setEnd(node, e)
  const span = document.createElement('span')
  span.className = HIGHLIGHT_CLASS
  span.setAttribute('data-thread-id', threadId)
  if (resolved) span.setAttribute('data-resolved', 'true')
  try {
    seg.surroundContents(span)
    return true
  } catch {
    // Segment boundary crosses an element edge — skip it.
    return false
  }
}

/** Wrap every text-node segment intersecting `range` in a highlight span. */
function wrapRange(range: Range, threadId: string, resolved: boolean): boolean {
  if (range.collapsed) return false
  let wrapped = false
  for (const node of intersectingTextNodes(range)) {
    if (wrapNodeSegment(node, range, threadId, resolved)) wrapped = true
  }
  return wrapped
}
