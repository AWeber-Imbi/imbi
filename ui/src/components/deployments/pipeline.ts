// Pure view-model helpers for the Deployments tab. The tab renders one
// detail pane per environment ("stage"); the stage *kind* decides which
// card the pane shows:
//
//   'commit'  — the entry environment (no upstream). Deploys raw commits
//               off the default branch; rolling back redeploys an older
//               commit. Never promotes.
//   'promote' — the upstream environment runs an untagged commit, so
//               moving it forward means cutting a new tag (promote).
//   'release' — the upstream environment already runs a tagged release,
//               so moving forward is deploying an existing tag; nothing
//               new is cut.
//
// The kind is derived from the *data* (does the upstream run a tag?), not
// from the environment's position or name, per the release-train spec.
//
// All commit/tag data comes from imbi's synced ClickHouse history
// (``/deployments/recent-commits`` + ``/deployments/release-history``),
// never the live source host — the sidebar's sync action refreshes it.
import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
  ReleaseHistoryEntry,
} from '@/types'

export interface PipelineStage {
  current: CurrentReleaseEnvironment | null
  /** History entry for the currently running release, if available. */
  currentHistoryEntry: null | ReleaseHistoryEntry
  env: Environment
  kind: StageKind
  /**
   * Commits deployed upstream but not here (newest first) — what a
   * promotion would tag. Only populated for promote stages.
   */
  pendingCommits: RecentCommit[]
  /** Tagged releases live upstream but not here (newest first). */
  pendingReleases: ReleaseHistoryEntry[]
  /**
   * Releases around the one this env runs (newest first), including the
   * current one and any that rank above it. See ``RecentRelease``.
   */
  recentReleases: RecentRelease[]
  upstream: Environment | null
  upstreamCurrent: CurrentReleaseEnvironment | null
}

/**
 * A release listed beside the env's current one. ``relation`` says which
 * side of the running release it falls on, so the row can offer a roll
 * back (``behind``) or a forward deploy (``ahead``) rather than assuming
 * everything listed is older.
 */
export interface RecentRelease {
  /**
   * Whether moving this env to the release is a legitimate forward move —
   * true only when it is also running (or already validated) upstream,
   * i.e. present in ``pendingReleases``. Always true for ``behind`` rows:
   * this env ran the release already. Never true for ``current``.
   */
  deployable: boolean
  entry: ReleaseHistoryEntry
  relation: ReleaseRelation
}

export type ReleaseRelation = 'ahead' | 'behind' | 'current'

export type StageKind = 'commit' | 'promote' | 'release'

// Releases listed either side of the running one, regardless of age.
// Rows ranking *above* current only appear after a rollback (or a
// roll-forward of an older line), so the window is symmetric.
const RELEASE_WINDOW = 10

/**
 * Build the per-environment stage models. ``environments`` must already be
 * sorted ascending by sort_order; ``history`` is the project's release
 * history, newest (highest semver) first; ``commits`` is the synced
 * commit history, newest first.
 */
export function buildPipeline(
  environments: Environment[],
  currentReleases: CurrentReleaseEnvironment[],
  history: ReleaseHistoryEntry[],
  commits: RecentCommit[],
): PipelineStage[] {
  const currentBySlug = new Map(
    currentReleases.map((row) => [row.environment.slug, row]),
  )
  // fallow-ignore-next-line complexity
  return environments.map((env, idx) => {
    const upstream = idx > 0 ? environments[idx - 1] : null
    const current = currentBySlug.get(env.slug) ?? null
    const upstreamCurrent = upstream
      ? (currentBySlug.get(upstream.slug) ?? null)
      : null
    const kind: StageKind = !upstream
      ? 'commit'
      : upstreamCurrent?.release?.tag
        ? 'release'
        : 'promote'
    // No kind guard: pendingReleases already returns [] when the upstream
    // runs no tag, which is what makes a stage 'promote' in the first
    // place, and when there is no upstream at all.
    const pending = pendingReleases(history, upstreamCurrent, current)
    const currentEntry = currentReleaseEntry(history, current)
    return {
      current,
      currentHistoryEntry: currentEntry,
      env,
      kind,
      pendingCommits:
        kind === 'promote' && upstreamCurrent?.release
          ? commitRange(
              commits,
              upstreamCurrent.release.committish,
              current?.release?.committish ?? null,
            )
          : [],
      pendingReleases: pending,
      recentReleases: recentReleases(history, current, currentEntry, pending),
      upstream,
      upstreamCurrent,
    }
  })
}

/**
 * Slice the synced commit history (newest first) from ``headSha``
 * (inclusive) down to ``baseSha`` (exclusive) — the commits that moving
 * ``baseSha`` forward to ``headSha`` would pick up. Falls back to the
 * remainder of the window when the base is older than the synced window,
 * and to ``[]`` when the head isn't in the history (or is not ahead).
 */
// fallow-ignore-next-line complexity
export function commitRange(
  commits: RecentCommit[],
  headSha: null | string,
  baseSha: null | string,
): RecentCommit[] {
  if (!headSha) return []
  const headIdx = commits.findIndex((c) => shaMatch(c.sha, headSha))
  if (headIdx < 0) return []
  if (!baseSha) return commits.slice(headIdx)
  const baseIdx = commits.findIndex((c) => shaMatch(c.sha, baseSha))
  if (baseIdx < 0) return commits.slice(headIdx)
  if (baseIdx <= headIdx) return []
  return commits.slice(headIdx, baseIdx)
}

/**
 * Semver-order two tags: negative when ``a`` ranks below ``b``, zero when
 * equal, ``null`` when either doesn't parse.
 */
export function compareTags(
  a: null | string | undefined,
  b: null | string | undefined,
): null | number {
  const keyA = semverKey(a)
  const keyB = semverKey(b)
  if (!keyA || !keyB) return null
  for (let i = 0; i < 3; i += 1) {
    if (keyA[i] !== keyB[i]) return keyA[i] - keyB[i]
  }
  return 0
}

/**
 * Default selection: the first environment as rendered — the sidebar is
 * descending sort order, so the last stage in pipeline order (e.g.
 * Production).
 */
export function defaultStageSlug(stages: PipelineStage[]): null | string {
  return stages[stages.length - 1]?.env.slug ?? null
}

/** SHA-prefix match in either direction (events may record short SHAs). */
export function shaMatch(a: string, b: string): boolean {
  return !!a && !!b && (a.startsWith(b) || b.startsWith(a))
}

/** History entry for the currently running release, if any. */
function currentReleaseEntry(
  history: ReleaseHistoryEntry[],
  current: CurrentReleaseEnvironment | null,
): null | ReleaseHistoryEntry {
  const release = current?.release
  if (!release?.tag) return null
  const tag = release.tag ?? null
  const idx = history.findIndex((entry) => tagEq(entry.tag, tag))
  if (idx >= 0) return history[idx]
  return entryFromRelease(release)
}

/** Minimal history entry for a release the tag sync hasn't recorded yet. */
function entryFromRelease(release: {
  committish: string
  created_at: string
  description?: null | string
  tag?: null | string
  title: string
}): ReleaseHistoryEntry {
  return {
    ci_status: 'unknown',
    notes_markdown: release.description ?? null,
    published_at: release.created_at,
    sha: release.committish,
    short_sha: release.committish.slice(0, 7),
    tag: release.tag ?? '',
    title: release.title,
  }
}

/**
 * Releases the env can deploy: everything at or below the upstream's
 * current tag (it has been validated upstream) but above this env's own
 * current tag. ``history`` is newest-first, so this is the slice between
 * the two tags. Empty when the upstream tag is unknown or the env is
 * already at (or ahead of) the upstream.
 */
// fallow-ignore-next-line complexity
function pendingReleases(
  history: ReleaseHistoryEntry[],
  upstreamCurrent: CurrentReleaseEnvironment | null,
  current: CurrentReleaseEnvironment | null,
): ReleaseHistoryEntry[] {
  const upstreamRelease = upstreamCurrent?.release
  const upstreamTag = upstreamRelease?.tag
  if (!upstreamTag) return []
  const envTag = current?.release?.tag ?? null
  // Truly in sync only when both run the same release.
  if (tagEq(upstreamTag, envTag)) return []
  const fromIdx = history.findIndex((entry) => tagEq(entry.tag, upstreamTag))
  if (fromIdx < 0) {
    // The upstream's tag hasn't reached the synced history yet — still
    // offer it (it is what's validated upstream).
    return [entryFromRelease(upstreamRelease)]
  }
  const toIdx = envTag
    ? history.findIndex((entry) => tagEq(entry.tag, envTag))
    : history.length
  if (toIdx >= 0 && toIdx <= fromIdx) {
    // The env ranks at or ahead of its upstream by semver but runs a
    // *different* release (divergent lines, or a roll-forward of an
    // older line). What's validated upstream stays deployable.
    return [history[fromIdx]]
  }
  const slice = history.slice(fromIdx, toIdx < 0 ? history.length : toIdx)
  if (toIdx >= 0 || !envTag) return slice
  // The env's tag isn't in the synced history — keep only entries that
  // semver-rank above it rather than treating all older releases as
  // pending.
  const envKey = semverKey(envTag)
  if (!envKey) return slice
  return slice.filter((entry) => {
    const key = semverKey(entry.tag)
    return !!key && semverLess(envKey, key)
  })
}

/**
 * The releases listed beside the env's current one — a window of
 * ``RELEASE_WINDOW`` either side, newest first, with the running release
 * in place between them.
 *
 * Rows above current are *not* filtered out: after a rollback (v5 → v4)
 * the release just left behind still belongs in the list, or it silently
 * disappears from the env's history. Whether it can be deployed again is
 * a separate question, answered by ``pending`` — only what is validated
 * upstream is offered as a forward move.
 */
// fallow-ignore-next-line complexity
function recentReleases(
  history: ReleaseHistoryEntry[],
  current: CurrentReleaseEnvironment | null,
  currentEntry: null | ReleaseHistoryEntry,
  pending: ReleaseHistoryEntry[],
): RecentRelease[] {
  const envTag = current?.release?.tag
  if (!currentEntry || !envTag) return []
  const currentRow: RecentRelease = {
    deployable: false,
    entry: currentEntry,
    relation: 'current',
  }
  const ahead = (entry: ReleaseHistoryEntry): RecentRelease => ({
    deployable: pending.some((rel) => tagEq(rel.tag, entry.tag)),
    entry,
    relation: 'ahead',
  })
  const behind = (entry: ReleaseHistoryEntry): RecentRelease => ({
    deployable: true,
    entry,
    relation: 'behind',
  })
  const idx = history.findIndex((entry) => tagEq(entry.tag, envTag))
  if (idx >= 0) {
    return [
      ...history.slice(Math.max(0, idx - RELEASE_WINDOW), idx).map(ahead),
      currentRow,
      ...history.slice(idx + 1, idx + 1 + RELEASE_WINDOW).map(behind),
    ]
  }
  // The env's tag isn't in the synced history (the tag sync hasn't caught
  // up, or it runs a divergent line) — fall back to semver ranking so the
  // list still renders with the running release in its right place. Tags
  // that don't parse, or that rank equal on a different tag string, sit on
  // neither side and are left out.
  if (!semverKey(envTag)) return []
  const above: ReleaseHistoryEntry[] = []
  const below: ReleaseHistoryEntry[] = []
  for (const entry of history) {
    const cmp = compareTags(envTag, entry.tag)
    if (cmp == null || cmp === 0) continue
    if (cmp < 0) above.push(entry)
    else below.push(entry)
  }
  return [
    ...above.slice(-RELEASE_WINDOW).map(ahead),
    currentRow,
    ...below.slice(0, RELEASE_WINDOW).map(behind),
  ]
}

/**
 * Best-effort semver ordering key — ``null`` when the tag doesn't parse.
 * Pre-release/build suffixes are ignored; this only backstops list
 * placement when a tag is missing from the synced history.
 */
function semverKey(tag: null | string | undefined): null | number[] {
  const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(tag ?? '')
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null
}

function semverLess(a: number[], b: number[]): boolean {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] < b[i]
  }
  return false
}

/** Tag equality tolerant of an optional leading ``v``. */
function tagEq(a: null | string | undefined, b: null | string): boolean {
  if (!a || !b) return false
  return a.replace(/^v/, '') === b.replace(/^v/, '')
}
