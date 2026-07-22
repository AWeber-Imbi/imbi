// Client-side grouping for activity feeds. The feed API returns a flat,
// newest-first list with no correlation/run id, so we approximate the
// "grouped run" shape from the mockups by clustering *consecutive* entries
// that share a key (actor + project) and fall within a time window of each
// other. A cluster of one renders as a single row; two or more collapse into
// an expandable group. See docs note in RecentActivity.tsx for where a
// backend `group_id` would replace this heuristic.

export interface ActivityCluster<T> {
  /** Cluster members, preserving the input (newest-first) order. */
  items: T[]
  /** Stable key for React lists and expand/collapse state. */
  key: string
  /** Newest member timestamp (ms since epoch). */
  newest: number
  /** Oldest member timestamp (ms since epoch). */
  oldest: number
}

export interface DaySection<T> {
  clusters: ActivityCluster<T>[]
  /** Local calendar-day key, e.g. `2026-07-16`. */
  key: string
  /** Human label: "Today", "Yesterday", "Jul 16", or "May 12, 2026". */
  label: string
}

interface ClusterOptions<T> {
  /** Members are grouped only when this key matches the running cluster. */
  keyOf: (item: T) => string
  /** Milliseconds since epoch for an item. */
  timeOf: (item: T) => number
  /** Max gap between adjacent members of one cluster. */
  windowMs: number
}

/**
 * Cluster a newest-first list into runs of adjacent, same-key items whose
 * neighbours are within `windowMs` of each other. Order is preserved.
 */
export function clusterConsecutive<T>(
  items: T[],
  { keyOf, timeOf, windowMs }: ClusterOptions<T>,
): ActivityCluster<T>[] {
  const clusters: ActivityCluster<T>[] = []
  let seq = 0
  for (const item of items) {
    const key = keyOf(item)
    const time = timeOf(item)
    const current = clusters[clusters.length - 1]
    const groupKey = current?.key.slice(0, current.key.lastIndexOf('#'))
    if (current && groupKey === key && current.oldest - time <= windowMs) {
      current.items.push(item)
      current.oldest = Math.min(current.oldest, time)
      current.newest = Math.max(current.newest, time)
    } else {
      clusters.push({
        items: [item],
        key: `${key}#${seq++}`,
        newest: time,
        oldest: time,
      })
    }
  }
  return clusters
}

/**
 * Bucket a newest-first list by local calendar day, then cluster within each
 * day. Sectioning first keeps clusters from straddling midnight.
 */
export function sectionByDay<T>(
  items: T[],
  options: ClusterOptions<T> & { now?: number },
): DaySection<T>[] {
  const now = options.now ?? Date.now()
  const sections: DaySection<T>[] = []
  const byKey = new Map<string, DaySection<T>>()
  for (const item of items) {
    const day = new Date(options.timeOf(item))
    const key = dayKey(day)
    let section = byKey.get(key)
    if (!section) {
      section = { clusters: [], key, label: dayLabel(day, now) }
      byKey.set(key, section)
      sections.push(section)
    }
    section.clusters.push(item as never)
  }
  // The bucket temporarily holds raw items in `clusters`; cluster them now.
  for (const section of sections) {
    section.clusters = clusterConsecutive(
      section.clusters as unknown as T[],
      options,
    )
  }
  return sections
}

function dayKey(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function dayLabel(d: Date, now: number): string {
  const today = new Date(now)
  if (dayKey(d) === dayKey(today)) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (dayKey(d) === dayKey(yesterday)) return 'Yesterday'
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() === today.getFullYear() ? {} : { year: 'numeric' }),
  })
}
