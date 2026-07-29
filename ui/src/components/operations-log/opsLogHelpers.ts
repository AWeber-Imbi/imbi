import { absTime, parseServerTs } from '@/lib/formatDate'
import type { OperationsLogRecord } from '@/types'

export { absTime }

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
  latestEntry: OperationsLogRecord
  project_slug: string
  stops: ReleaseStop[]
  version: string
}

export interface ReleaseStop {
  entry: OperationsLogRecord
  environment_slug: string
}

export type TimeRange = '7d' | '24h' | '30d' | '90d' | 'all'

// Cheap targeted read of `commit_sha` out of the plugin-owned JSON
// description. Grouping walks every loaded entry, so we skip a full
// JSON.parse per row; the value is a hex committish, so there is no
// escaping to honour.
const COMMIT_SHA_RE = /"commit_sha"\s*:\s*"([^"]+)"/

interface DayBucketKey {
  date: Date
  key: string
  label: string
}

// Grouping bookkeeping that never leaves this module: `envIndex` makes
// the earliest-wins stop merge O(1) instead of a findIndex scan,
// `stopMs`/`latestMs` cache parsed timestamps, and `slot` is the train's
// position in the output so a merge can vacate the loser's row.
interface ReleaseBucket {
  envIndex: Map<string, number>
  group: ReleaseGroup
  latestMs: number
  slot: number
  stopMs: number[]
  tagged: boolean
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
    const dk = dayKeyFromDate(parseServerTs(iso), todayMs)
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

// Group every deploy of one release into a single release train.
//
// A release has two identities and the environments it passes through
// don't all know both: an untagged deploy (testing ships straight off a
// commit) records the committish as its `version`, while the promotion
// that tags it records the tag as `version` and the same committish as
// `commit_sha`. So an entry joins a train when it shares *either* the
// version or the committish with it, and the train displays the tag once
// any of its stops carries one. The JSON description payload differs per
// action (`deploy` / `promote` / `redeploy`), so it is never an identity.
//
// Entries arrive newest-first; a train renders in the slot of its newest
// entry. Rows that aren't versioned deploys stay ungrouped.
export function groupReleases(entries: OperationsLogRecord[]): FeedItem[] {
  const byKey = new Map<string, ReleaseBucket>()
  // Slots of trains absorbed by a merge are nulled out rather than
  // spliced, so surviving slot indices stay valid while we iterate.
  const order: (FeedItem | null)[] = []
  for (const e of entries) {
    const version = (e.version || '').trim()
    if (e.entry_type !== 'Deployed' || !version) {
      order.push({ entry: e, kind: 'single' })
      continue
    }
    const sha = commitShaOf(e)
    const keys = [`${e.project_slug}::v:${version}`]
    if (sha) keys.push(`${e.project_slug}::c:${sha}`)
    const occurredMs = toMs(e.occurred_at)
    // Both keys can already point at trains built from entries that only
    // knew one identity each -- that's the signal to fuse them.
    let bucket: ReleaseBucket | undefined
    for (const key of keys) {
      const found = byKey.get(key)
      if (!found) continue
      bucket =
        !bucket || found === bucket
          ? found
          : mergeBuckets(bucket, found, order, byKey)
    }
    if (!bucket) {
      bucket = {
        envIndex: new Map(),
        group: {
          latestEntry: e,
          project_slug: e.project_slug,
          stops: [],
          version,
        },
        latestMs: occurredMs,
        slot: order.length,
        stopMs: [],
        tagged: false,
      }
      order.push({ group: bucket.group, kind: 'release' })
    }
    for (const key of keys) byKey.set(key, bucket)
    addStop(bucket, e, occurredMs)
    // A tag beats a bare committish as the train's display version; the
    // first tag encountered (the newest) wins.
    if (!bucket.tagged && version !== sha) {
      bucket.group.version = version
      bucket.tagged = true
    }
    if (occurredMs > bucket.latestMs) {
      bucket.group.latestEntry = e
      bucket.latestMs = occurredMs
    }
  }
  return order.filter((item): item is FeedItem => item !== null)
}

export { relTime } from '@/lib/formatDate'

// Return occurred_at as milliseconds without allocating a Date object.
// Hot path: called from sort comparators and filter loops over thousands
// of entries per incremental page. `Date.parse` is native-optimised for
// ISO 8601 and is ~2× faster than `new Date(s).getTime()` while skipping
// the allocation that causes GC pressure during bulk loads.
export function toMs(iso: string): number {
  return Date.parse(iso)
}

function addStop(
  bucket: ReleaseBucket,
  entry: OperationsLogRecord,
  occurredMs: number,
): void {
  const envSlug = entry.environment_slug
  const existingIdx = bucket.envIndex.get(envSlug)
  if (existingIdx === undefined) {
    bucket.envIndex.set(envSlug, bucket.group.stops.length)
    bucket.group.stops.push({ entry, environment_slug: envSlug })
    bucket.stopMs.push(occurredMs)
    return
  }
  // Keep the earliest deploy into each env: that's when the release
  // reached it, not when it was last redeployed there.
  if (occurredMs < bucket.stopMs[existingIdx]!) {
    bucket.group.stops[existingIdx] = { entry, environment_slug: envSlug }
    bucket.stopMs[existingIdx] = occurredMs
  }
}

function commitShaOf(entry: OperationsLogRecord): string {
  return COMMIT_SHA_RE.exec(entry.description ?? '')?.[1] ?? ''
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

// Fuse two trains that turned out to be the same release. The one in the
// earlier (newer) slot survives so the fused train keeps the newest
// entry's position in the feed; the loser's slot is vacated and every key
// pointing at it is repointed.
function mergeBuckets(
  a: ReleaseBucket,
  b: ReleaseBucket,
  order: (FeedItem | null)[],
  byKey: Map<string, ReleaseBucket>,
): ReleaseBucket {
  const [keep, drop] = a.slot <= b.slot ? [a, b] : [b, a]
  drop.group.stops.forEach((stop, i) => {
    addStop(keep, stop.entry, drop.stopMs[i]!)
  })
  if (drop.latestMs > keep.latestMs) {
    keep.group.latestEntry = drop.group.latestEntry
    keep.latestMs = drop.latestMs
  }
  if (!keep.tagged && drop.tagged) {
    keep.group.version = drop.group.version
    keep.tagged = true
  }
  order[drop.slot] = null
  for (const [key, bucket] of byKey) {
    if (bucket === drop) byKey.set(key, keep)
  }
  return keep
}
