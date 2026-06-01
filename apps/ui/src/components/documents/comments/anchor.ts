// Text-quote anchoring helpers for inline document comments.
//
// Anchors are W3C/Hypothesis-style: an exact `quote`, ~32 chars of `prefix`
// and `suffix` for disambiguation, and a `start` character offset. Offsets and
// prefix/suffix are computed against the *rendered* text content of the article
// (the concatenation of its visible text nodes), and resolution searches that
// same rendered text — so capture and re-resolution are symmetric and never
// depend on the non-invertible markdown→DOM mapping. The document's markdown
// source is never mutated; highlights are an overlay re-applied on each render.

import type { CommentAnchor } from '@/types/comments'

const CONTEXT = 32

interface TextPoint {
  node: Text
  offset: number
}

/**
 * Derive an anchor from the current selection inside `root`. Returns null when
 * the selection is empty or lies outside the article.
 */
// fallow-ignore-next-line complexity
export function anchorFromSelection(root: HTMLElement): CommentAnchor | null {
  const range = selectionRange(root)
  if (!range) return null
  const quote = range.toString().trim()
  if (!quote) return null

  const nodes = textNodes(root)
  const full = nodes.map((n) => n.nodeValue ?? '').join('')
  const start = pointOffset(nodes, range.startContainer, range.startOffset)
  if (start === null) return null
  // Use the trimmed quote's true start within the full text for stability.
  const quoteStart = full.indexOf(quote, Math.max(0, start - quote.length))
  const resolvedStart = quoteStart >= 0 ? quoteStart : start
  return {
    prefix: full.slice(Math.max(0, resolvedStart - CONTEXT), resolvedStart),
    quote,
    start: resolvedStart,
    suffix: full.slice(
      resolvedStart + quote.length,
      resolvedStart + quote.length + CONTEXT,
    ),
  }
}

/**
 * Resolve an anchor to a DOM Range within `root`, disambiguating repeated
 * quotes by prefix/suffix and the recorded start offset. Returns null when the
 * quote can no longer be found (the thread becomes "orphaned").
 */
// fallow-ignore-next-line complexity
export function resolveAnchor(
  root: HTMLElement,
  anchor: CommentAnchor,
): null | Range {
  if (!anchor.quote) return null
  const nodes = textNodes(root)
  const full = nodes.map((n) => n.nodeValue ?? '').join('')
  const best = bestOccurrence(full, anchor)
  if (best === null) return null

  const startPoint = offsetPoint(nodes, best)
  const endPoint = offsetPoint(nodes, best + anchor.quote.length)
  if (!startPoint || !endPoint) return null
  const range = document.createRange()
  range.setStart(startPoint.node, startPoint.offset)
  range.setEnd(endPoint.node, endPoint.offset)
  return range
}

/** The highest-scoring occurrence index of the anchor's quote, or null. */
function bestOccurrence(full: string, anchor: CommentAnchor): null | number {
  const hits = occurrences(full, anchor.quote)
  if (!hits.length) return null
  let best = hits[0]
  let bestScore = -Infinity
  for (const i of hits) {
    const s = scoreCandidate(full, i, anchor)
    if (s > bestScore) {
      bestScore = s
      best = i
    }
  }
  return best
}

/** Find every occurrence of `quote` in `full`. */
function occurrences(full: string, quote: string): number[] {
  const out: number[] = []
  let from = 0
  for (;;) {
    const i = full.indexOf(quote, from)
    if (i < 0) break
    out.push(i)
    from = i + Math.max(1, quote.length)
  }
  return out
}

/** Locate the (node, offset) point at a rendered-text character offset. */
// fallow-ignore-next-line complexity
function offsetPoint(nodes: Text[], target: number): null | TextPoint {
  let total = 0
  for (const n of nodes) {
    const len = n.nodeValue?.length ?? 0
    if (target <= total + len) return { node: n, offset: target - total }
    total += len
  }
  return null
}

/** Character offset of a (node, offset) point within the root's rendered text. */
// fallow-ignore-next-line complexity
function pointOffset(nodes: Text[], node: Node, offset: number): null | number {
  let total = 0
  for (const n of nodes) {
    if (n === node) return total + offset
    total += n.nodeValue?.length ?? 0
  }
  return null
}

/**
 * Score a candidate occurrence of `quote` at `index` in `full` against the
 * anchor's prefix/suffix/start. Higher is better.
 */
// fallow-ignore-next-line complexity
function scoreCandidate(
  full: string,
  index: number,
  anchor: CommentAnchor,
): number {
  let score = 0
  const before = full.slice(Math.max(0, index - anchor.prefix.length), index)
  if (anchor.prefix && before.endsWith(anchor.prefix)) score += 2
  const after = full.slice(
    index + anchor.quote.length,
    index + anchor.quote.length + anchor.suffix.length,
  )
  if (anchor.suffix && after.startsWith(anchor.suffix)) score += 2
  // Proximity to the recorded start breaks remaining ties.
  score += 1 - Math.min(1, Math.abs(index - anchor.start) / 2000)
  return score
}

/** The current selection's range if it is non-empty and inside `root`. */
// fallow-ignore-next-line complexity
function selectionRange(root: HTMLElement): null | Range {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const range = sel.getRangeAt(0)
  if (!root.contains(range.commonAncestorContainer)) return null
  return range
}

/** Collect the article's non-empty text nodes in document order. */
function textNodes(root: HTMLElement): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.nodeValue && node.nodeValue.length > 0
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT,
  })
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  return nodes
}
