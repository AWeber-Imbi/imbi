import { LABEL_SWATCHES } from '@/lib/chip-colors'
import type { Document, TagRef } from '@/types'

/**
 * Deterministic color for a tag slug. Stable hash keeps each tag on the same
 * swatch across renders without requiring color in the API schema.
 */
export function colorForTag(slug: string): string {
  let hash = 0
  for (let i = 0; i < slug.length; i++) {
    hash = (hash * 31 + slug.charCodeAt(i)) | 0
  }
  const idx = Math.abs(hash) % LABEL_SWATCHES.length
  return LABEL_SWATCHES[idx].hex
}

const TITLE_MAX = 120
const EXCERPT_MAX = 240

/** First paragraph of body text (after title), stripped of basic markdown. */
export function deriveExcerpt(content: string): string {
  const lines = content.split('\n')
  let sawTitle = false
  const buf: string[] = []
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      if (buf.length) break
      continue
    }
    if (!sawTitle && /^#{1,6}\s+/.test(line)) {
      sawTitle = true
      continue
    }
    sawTitle = true
    if (/^[-*+]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      buf.push(line.replace(/^[-*+]\s+|^\d+\.\s+/, ''))
      continue
    }
    if (/^[#>`|]/.test(line)) continue
    buf.push(line)
  }
  const text = buf
    .join(' ')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  return truncate(text, EXCERPT_MAX)
}

/**
 * Prefer the document's explicit title; fall back to the first heading or line
 * of content for rows written before the title column existed.
 */
export function documentTitle(document: Document): string {
  const explicit = (document.title ?? '').trim()
  if (explicit) return truncate(explicit, TITLE_MAX)
  const lines = document.content.split('\n')
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    const heading = line.match(/^#{1,6}\s+(.+?)\s*#*$/)
    if (heading) return truncate(heading[1], TITLE_MAX)
    return truncate(line.replace(/^[*_>`~-]+\s*/, ''), TITLE_MAX)
  }
  return 'Untitled document'
}

export function formatFull(iso: null | string | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

export function formatUpdated(document: Document): string {
  const iso = document.updated_at ?? document.created_at
  return relativeShort(iso)
}

export function initials(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function relativeShort(iso: null | string | undefined): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ''
  const diff = Date.now() - then
  const m = Math.round(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  if (d < 14) return `${d}d ago`
  const w = Math.round(d / 7)
  if (w < 8) return `${w}w ago`
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s
  return s.slice(0, max - 1).trimEnd() + '…'
}

export const EMPTY_ACTIVE: ReadonlySet<string> = new Set()

export function tagCounts(documents: Document[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const n of documents) {
    for (const t of n.tags) counts[t.slug] = (counts[t.slug] ?? 0) + 1
  }
  return counts
}

/** Dedupe tags by slug across the whole document list. */
export function uniqueTagsFromDocuments(documents: Document[]): TagRef[] {
  const seen = new Map<string, TagRef>()
  for (const n of documents) {
    for (const t of n.tags) {
      if (!seen.has(t.slug)) seen.set(t.slug, t)
    }
  }
  return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name))
}
