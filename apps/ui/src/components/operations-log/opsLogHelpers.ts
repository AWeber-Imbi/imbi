import type { OperationsLogRecord } from '@/types'

export interface DayBucket {
  date: Date
  items: FeedItem[]
  key: string
  label: string
}

export type FeedItem =
  | { entry: OperationsLogRecord; kind: 'single' }
  | { group: ReleaseGroup; kind: 'release' }

export type OperationsLogView = 'grouped' | 'stream'

export interface ReleaseGroup {
  description: string
  latestEntry: OperationsLogRecord
  project_slug: string
  stops: ReleaseStop[]
}

export interface ReleaseStop {
  entry: OperationsLogRecord
  environment_slug: string
}

export type TimeRange = '7d' | '24h' | '30d' | '90d' | 'all'

interface DayBucketKey {
  date: Date
  key: string
  label: string
}

export function absTime(iso: string): string {
  return parseUtcIso(iso).toLocaleString(undefined, {
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function bucketByDay(
  items: FeedItem[],
  now: number = Date.now(),
): DayBucket[] {
  // Compute today's local-midnight once — `dayKey` used to redo this per
  // call, allocating 2 Date objects per item.
  const n = new Date(now)
  const todayMs = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime()
  const buckets: DayBucket[] = []
  let current: DayBucket | null = null
  for (const it of items) {
    const iso =
      it.kind === 'release'
        ? it.group.latestEntry.occurred_at
        : it.entry.occurred_at
    const dk = dayKeyFromDate(parseUtcIso(iso), todayMs)
    if (!current || current.key !== dk.key) {
      current = { date: dk.date, items: [], key: dk.key, label: dk.label }
      buckets.push(current)
    }
    current.items.push(it)
  }
  return buckets
}

// Strip a leading "release X.Y.Z" / "release X.Y.Z - " from a description
// when it just repeats the version already shown in the row.
export function cleanDescription(
  description: null | string | undefined,
  version: null | string | undefined,
): string {
  const desc = (description || '').trim()
  if (!version) return desc
  const lower = desc.toLowerCase()
  const prefix = `release ${version.toLowerCase()}`
  if (lower.startsWith(prefix)) {
    return desc
      .substring(`release ${version}`.length)
      .replace(/^\s*[-–—:]\s*/, '')
      .trim()
  }
  return desc
}

export function cleanName(email: null | string | undefined): string {
  if (!email) return 'system'
  const part = email.split('@')[0]
  return part || email
}

// Group contiguous same-version deploys of one project into a single
// release train. Keys by `project_slug::description` — the API emits the
// same description for each env a single release moves through.
export function groupReleases(entries: OperationsLogRecord[]): FeedItem[] {
  // envIndexByGroup tracks env→stops index so the "earliest-wins" merge
  // is O(1) instead of findIndex (avoids O(stops²) per group).
  // latestMs tracks the group's current newest occurred_at in ms so we
  // avoid re-parsing on every comparison.
  const groups = new Map<string, ReleaseGroup>()
  const envIndexByGroup = new Map<string, Map<string, number>>()
  const latestMsByGroup = new Map<string, number>()
  const stopMsByGroup = new Map<string, number[]>()
  const order: FeedItem[] = []
  for (const e of entries) {
    if (e.entry_type !== 'Deployed') {
      order.push({ entry: e, kind: 'single' })
      continue
    }
    const descKey = (e.description || '').trim()
    const key = `${e.project_slug}::${descKey}`
    const occurredMs = toMs(e.occurred_at)
    let g = groups.get(key)
    if (!g) {
      g = {
        description: descKey,
        latestEntry: e,
        project_slug: e.project_slug,
        stops: [],
      }
      groups.set(key, g)
      envIndexByGroup.set(key, new Map())
      latestMsByGroup.set(key, occurredMs)
      stopMsByGroup.set(key, [])
      order.push({ group: g, kind: 'release' })
    }
    const envIndex = envIndexByGroup.get(key)!
    const stopMs = stopMsByGroup.get(key)!
    const envSlug = e.environment_slug
    const existingIdx = envIndex.get(envSlug)
    if (existingIdx !== undefined) {
      // Keep the earliest deploy into each env.
      if (occurredMs < stopMs[existingIdx]) {
        g.stops[existingIdx] = { entry: e, environment_slug: envSlug }
        stopMs[existingIdx] = occurredMs
      }
    } else {
      envIndex.set(envSlug, g.stops.length)
      g.stops.push({ entry: e, environment_slug: envSlug })
      stopMs.push(occurredMs)
    }
    const latestMs = latestMsByGroup.get(key)!
    if (occurredMs > latestMs) {
      g.latestEntry = e
      latestMsByGroup.set(key, occurredMs)
    }
  }
  return order
}

export function relTime(iso: string, now: number = Date.now()): string {
  const t = toMs(iso)
  const diff = Math.max(0, now - t)
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d`
  return `${Math.floor(d / 7)}w`
}

// Return occurred_at as milliseconds without allocating a Date object.
// Hot path: called from sort comparators and filter loops over thousands
// of entries per incremental page. `Date.parse` is native-optimised for
// ISO 8601 and is ~2× faster than `new Date(s).getTime()` while skipping
// the allocation that causes GC pressure during bulk loads.
export function toMs(iso: string): number {
  return Date.parse(iso)
}

function dayKeyFromDate(d: Date, todayMs: number): DayBucketKey {
  const eventDay = new Date(
    d.getFullYear(),
    d.getMonth(),
    d.getDate(),
  ).getTime()
  const diffDays = Math.round((todayMs - eventDay) / 86_400_000)
  if (diffDays === 0) return { date: d, key: 'today', label: 'Today' }
  if (diffDays === 1) return { date: d, key: 'yesterday', label: 'Yesterday' }
  return {
    date: d,
    key: d.toDateString(),
    label: d.toLocaleDateString(undefined, { weekday: 'long' }),
  }
}

function parseUtcIso(iso: string): Date {
  return new Date(iso)
}
