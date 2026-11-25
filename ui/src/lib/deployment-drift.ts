// Environment drift: whether what's deployed in one environment differs
// from the next one down the pipeline. The projects list reads the
// server's verdict (`drift_pairs`, `release_drifted`); the project detail
// tabs, which have live deployment status, use these helpers.
// Pairs come from `environment-chains`: adjacent environments within one
// pipeline, never across a `terminal` boundary (#285).

import { splitChains } from '@/lib/environment-chains'
import { parseServerTs } from '@/lib/formatDate'

export interface DriftEnvironment {
  label_color?: null | string
  name: string
  slug: string
  sort_order?: null | number
  terminal?: boolean | null
}

export interface DriftPair {
  /** The two endpoints, when both sides have one. The range that would
   *  need promoting runs from `baseSha` (what the later environment
   *  runs) up to `headSha` (what the earlier one runs). */
  baseSha: null | string
  drifted: boolean
  from: string
  headSha: null | string
  to: string
  toSlug: string
}

/**
 * The per-commit drift rule, in one place: a commit is clean only when
 * its verdict is explicitly `false`. A `true` verdict or an unanswered
 * commit (`null`/absent) both fail closed as drifted.
 */
export function commitDrifted(commit: {
  drift_detected?: boolean | null
}): boolean {
  return commit.drift_detected !== false
}

export function computeDriftPairs(
  environments: DriftEnvironment[],
  releases: Record<string, { committish?: null | string; tag?: null | string }>,
): DriftPair[] {
  const pairs: DriftPair[] = []
  for (const chain of splitChains(environments)) {
    for (let i = 0; i < chain.length - 1; i++) {
      const a = chain[i]
      const b = chain[i + 1]
      const ra = releases[a.slug]
      const rb = releases[b.slug]
      const aTag = ra?.tag ?? null
      const bTag = rb?.tag ?? null
      const aSha = ra?.committish ?? null
      const bSha = rb?.committish ?? null
      // When both envs have a SHA, compare them directly so that a tag-only
      // difference on identical commits does not register as drift.
      // Otherwise fall back to tag-or-SHA equality.
      const drifted =
        aSha && bSha ? aSha !== bSha : (aTag ?? aSha) !== (bTag ?? bSha)
      pairs.push({
        baseSha: bSha,
        drifted,
        from: a.name,
        headSha: aSha,
        to: b.name,
        toSlug: b.slug,
      })
    }
  }
  return pairs
}

// Whether this promotion step needs acting on. Only proven clean is
// clean: the pair is suppressed when the server evaluated its range and
// every commit carried a `false` verdict. A `true` verdict, an
// unanswered commit, or a range the server could not evaluate at all
// (absent key, missing committish) each mean show it -- an unverified
// difference is still work someone must look at. Only called for pairs
// `computeDriftPairs` marked drifted, so equal pairs never reach the
// fail-closed branches.
export function rangeNeedsAction(
  ranges: Record<string, boolean> | undefined,
  pair: DriftPair,
): boolean {
  if (!pair.baseSha || !pair.headSha) return true
  return ranges?.[`${pair.baseSha}..${pair.headSha}`] !== false
}

// Whether the tag..HEAD verdict proves the unreleased commits clean. A
// project with no tag has no evaluated range, so its `false` default is
// not a verdict and does not count.
export function releaseRangeClean(
  summary:
    | null
    | undefined
    | { drift_detected?: boolean; latest_tag: null | string },
): boolean {
  return !!summary?.latest_tag && summary.drift_detected === false
}

const DURATION_UNITS_MS: Record<string, number> = {
  d: 86_400_000,
  h: 3_600_000,
  m: 60_000,
  w: 604_800_000,
}

// A duration such as `90m`, `12h`, `3d`, or `2w`, in ms. Null when the
// value is empty or does not parse.
export function parseDuration(raw: null | string | undefined): null | number {
  const match = raw?.trim().match(/^(\d+)\s*([mhdw])$/i)
  if (!match) return null
  return Number(match[1]) * DURATION_UNITS_MS[match[2].toLowerCase()]
}

// Caddy writes VITE_DRIFT_STALE_AFTER into index.html at request time.
// Without a templater the placeholder arrives literally; fall back to
// the build-time value.
function resolveStaleAfter(): null | number {
  const runtime = window.__IMBI_DRIFT_STALE_AFTER__
  return parseDuration(
    runtime && !runtime.includes('{{')
      ? runtime
      : import.meta.env.VITE_DRIFT_STALE_AFTER,
  )
}

const DRIFT_STALE_AFTER_MS = resolveStaleAfter()

// Whether a change waiting since `since` has waited longer than the
// configured threshold. Always false when no threshold is configured or
// the server has no date.
export function driftIsStale(
  since: null | string | undefined,
  staleAfterMs: null | number = DRIFT_STALE_AFTER_MS,
): boolean {
  if (!since || staleAfterMs === null) return false
  return Date.now() - parseServerTs(since).getTime() > staleAfterMs
}
