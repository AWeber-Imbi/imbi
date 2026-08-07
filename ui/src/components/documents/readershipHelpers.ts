import type { DocumentReader } from '@/types'

/**
 * How completely one person got through a document.
 *
 * `engaged` is deliberately the same rule the server uses to set
 * `is_read` (see `classify()` in `_document_reads.py`): 80% scroll depth
 * *or* dwelling for the document's estimated read time — long documents
 * qualify by scrolling, short ones by dwelling. `skimmed` is the same
 * test at half the bar, so the three bands partition every reader
 * without a gap.
 */
export type EngagementBand = 'brief' | 'engaged' | 'skimmed'

/** Scroll depth at which a long document counts as read (server: READ_SCROLL_PCT). */
const READ_SCROLL_PCT = 80

export const BAND_LABEL: Record<EngagementBand, string> = {
  brief: 'Brief',
  engaged: 'Engaged',
  skimmed: 'Skimmed',
}

/** Chip treatment per band — success / warning / neutral, never colour alone. */
export const BAND_CHIP: Record<EngagementBand, string> = {
  brief: 'bg-secondary text-secondary border-tertiary',
  engaged: 'bg-success text-success border-success',
  skimmed: 'bg-warning text-warning border-warning',
}

/** Fill colour for the depth bar, matching the band it represents. */
export const BAND_BAR: Record<EngagementBand, string> = {
  brief: 'bg-tertiary',
  engaged: 'bg-success',
  skimmed: 'bg-warning',
}

/** Tally of readers per band, in the order the summary tiles show them. */
export function bandCounts(
  readers: DocumentReader[],
  estimatedReadSeconds: number,
): Record<EngagementBand, number> {
  const counts: Record<EngagementBand, number> = {
    brief: 0,
    engaged: 0,
    skimmed: 0,
  }
  for (const reader of readers) counts[bandFor(reader, estimatedReadSeconds)]++
  return counts
}

export function bandFor(
  reader: DocumentReader,
  estimatedReadSeconds: number,
): EngagementBand {
  // How far through the document this reader got, by whichever measure
  // says more: scroll for a long document, dwell for a short one. 1.0 is
  // the server's read threshold; half of it is the skim threshold.
  const byDepth = reader.max_scroll_pct / READ_SCROLL_PCT
  const byDwell =
    estimatedReadSeconds > 0 ? reader.engaged_seconds / estimatedReadSeconds : 0
  const progress = Math.max(byDepth, byDwell)
  if (progress >= 1) return 'engaged'
  return progress >= 0.5 ? 'skimmed' : 'brief'
}

/** Engaged time as `9m 12s` — precise enough to compare two readers. */
export function formatDwell(seconds: number): string {
  if (seconds <= 0) return '—'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60)
    return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

/** Estimated read time as the coarse `6 min read` byline. */
export function formatReadTime(seconds: number): null | string {
  if (seconds <= 0) return null
  return `${Math.max(1, Math.round(seconds / 60))} min read`
}

/** Reading speed the server uses to derive a document's read estimate. */
const WORDS_PER_MINUTE = 220

/**
 * The same estimate the server computes from a document's content
 * (`estimated_read_ms` in `_document_reads.py`). Derived here so the
 * byline can show it without waiting on the analytics request.
 */
export function estimatedReadSeconds(content: string): number {
  const words = content.split(/\s+/).filter(Boolean).length
  if (!words) return 0
  return Math.round((words / WORDS_PER_MINUTE) * 60)
}
