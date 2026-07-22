// Adapters that project the flat `ActivityFeedEntry` union onto the generic
// grouping primitives, plus per-entry and per-cluster presentation helpers
// (tone, status verb, cluster summary). Kept free of JSX so it stays unit
// testable alongside grouping.ts.

import { isBotActor } from '@/components/ui/user-identity'
import type { ActivityFeedEntry, OperationsLogEntry } from '@/types'

import type { Tone } from './tone'

/**
 * Window within which consecutive same-actor+project entries collapse into one
 * group. A backend correlation/run id would make this exact; until then an
 * hour approximates a "burst" (a CI run, a config edit session).
 */
export const ACTIVITY_GROUP_WINDOW_MS = 60 * 60 * 1000

/** Actor + project so a CI burst on one project groups but unrelated work does not. */
export function entryClusterKey(entry: ActivityFeedEntry): string {
  const actor = (entry.email_address || entry.display_name || '').toLowerCase()
  const project = entry.project_name ?? `#${entry.project_id ?? ''}`
  return `${actor}|${project}`
}

export function entryIsBot(entry: ActivityFeedEntry): boolean {
  return isBotActor(entry.display_name) || isBotActor(entry.email_address)
}

export function entryProjectName(entry: ActivityFeedEntry): null | string {
  return entry.project_name ?? null
}

export function entryTimeIso(entry: ActivityFeedEntry): string | undefined {
  return (
    entry.occurred_at ??
    (entry.type === 'ProjectFeedEntry' ? entry.when : undefined) ??
    undefined
  )
}

export function entryTimeMs(entry: ActivityFeedEntry): number {
  const iso =
    entry.occurred_at ??
    (entry.type === 'ProjectFeedEntry' ? entry.when : undefined)
  const ms = iso ? Date.parse(iso) : NaN
  return Number.isFinite(ms) ? ms : 0
}

const CHANGE_TYPE_TONE: Record<OperationsLogEntry['change_type'], Tone> = {
  Configured: 'neutral',
  Decommissioned: 'danger',
  Deployed: 'success',
  Migrated: 'info',
  Provisioned: 'info',
  Restarted: 'info',
  'Rolled Back': 'danger',
  Scaled: 'info',
  Upgraded: 'info',
}

export interface ClusterMeta {
  statusLabel: string
  /** e.g. "3 activities" or (breakdown) "2 deployed · 1 configured". */
  summary: string
  tone: Tone
}

/**
 * Roll a cluster's members up into a single tone + status label + summary.
 * `showBreakdown` swaps the plain count for a per-verb breakdown.
 */
export function clusterMeta(
  items: ActivityFeedEntry[],
  showBreakdown: boolean,
): ClusterMeta {
  const tones = items.map(entryTone)
  const tone: Tone = tones.includes('danger')
    ? 'danger'
    : tones.every((t) => t === 'success')
      ? 'success'
      : entryTone(items[0])

  const verbCounts = new Map<string, number>()
  for (const item of items) {
    const verb = entryVerb(item)
    verbCounts.set(verb, (verbCounts.get(verb) ?? 0) + 1)
  }
  const statusLabel = verbCounts.size === 1 ? entryVerb(items[0]) : 'activity'

  let summary: string
  if (showBreakdown) {
    summary = [...verbCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([verb, count]) => `${count} ${verb}`)
      .join(' · ')
  } else {
    summary = `${items.length} activities`
  }
  return { statusLabel, summary, tone }
}

/** Compact "target" label for an expanded event row (environment/version/type). */
export function entryEventLabel(entry: ActivityFeedEntry): string {
  if (entry.type === 'OperationsLogEntry') {
    if (entry.environment) {
      return entry.version
        ? `${entry.environment} · ${entry.version}`
        : entry.environment
    }
    return entry.version ?? entry.change_type
  }
  return entry.project_type || entry.what
}

/** Namespace/team label for the widget header, when the entry carries one. */
export function entryNamespace(entry: ActivityFeedEntry): null | string {
  return entry.type === 'ProjectFeedEntry' ? (entry.namespace ?? null) : null
}

/** Project type label for the widget header, when the entry carries one. */
export function entryProjectType(entry: ActivityFeedEntry): null | string {
  return entry.type === 'ProjectFeedEntry' ? (entry.project_type ?? null) : null
}

/** One-line action summary for a single row, without repeating the project. */
export function entrySummaryText(entry: ActivityFeedEntry): string {
  if (entry.type === 'OperationsLogEntry') {
    const parts = [entry.change_type.toLowerCase()]
    if (entry.version) parts.push(entry.version)
    if (entry.environment) parts.push(`to ${entry.environment}`)
    return parts.join(' ')
  }
  return entry.what === 'updated facts' ? 'updated facts' : entry.what
}

export function entryTone(entry: ActivityFeedEntry): Tone {
  if (entry.type === 'OperationsLogEntry') {
    return CHANGE_TYPE_TONE[entry.change_type] ?? 'neutral'
  }
  return entry.what === 'created' ? 'accent' : 'neutral'
}

/** Short verb for a status chip, e.g. "deployed", "created", "updated facts". */
export function entryVerb(entry: ActivityFeedEntry): string {
  return entry.type === 'OperationsLogEntry'
    ? entry.change_type.toLowerCase()
    : entry.what
}
