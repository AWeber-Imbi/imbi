// Client-side grouping for activity feeds. The feed API returns a flat,
// newest-first list with no correlation/run id, so we approximate the
// "grouped run" shape from the mockups by clustering *consecutive* entries
// that share a key (actor + project) and fall within a time window of each
// other. A cluster of one renders as a single row; two or more collapse into
// an expandable group. A backend `group_id` would replace
// this heuristic.

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
