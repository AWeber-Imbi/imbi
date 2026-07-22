import type { ActivityFeedEntry } from '@/types'

import { clusterMeta, entryTone } from './entryAdapters'
import type { ClusterMeta } from './entryAdapters'
import type { ActivityCluster } from './grouping'
import type { Tone } from './tone'

export interface ClusterView {
  isGroup: boolean
  lead: ActivityFeedEntry
  meta: ClusterMeta
  tone: Tone
}

/** Shared view-model for a cluster row: is it a group, its lead entry, roll-up, and tone. */
export function clusterView(
  cluster: ActivityCluster<ActivityFeedEntry>,
): ClusterView {
  const isGroup = cluster.items.length > 1
  const lead = cluster.items[0]
  const meta = clusterMeta(cluster.items, true)
  return { isGroup, lead, meta, tone: isGroup ? meta.tone : entryTone(lead) }
}
