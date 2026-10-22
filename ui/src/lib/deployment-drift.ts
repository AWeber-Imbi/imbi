// Environment drift: whether what's deployed in one environment differs
// from the next one down the pipeline. Shared by the projects list (drift
// filters + badges) and the project detail tabs so both agree on the rule.
// Pairs come from `environment-chains`: adjacent environments within one
// pipeline, never across a `terminal` boundary (#285).

import { splitChains } from '@/lib/environment-chains'

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
  toLabelColor?: null | string
  toSlug: string
}

// The project fields the drift rule reads, in one place. Declared here
// rather than inline at each call site so a field added to the rule
// cannot reach some consumers and miss others.
export interface DriftProject {
  current_releases?: null | Record<
    string,
    { committish?: null | string; tag?: null | string }
  >
  /** `"<base>..<head>"` -> whether that range needs action. `false`
   *  means every commit in it carries a CI verdict of `false`; `true`
   *  means a `true` verdict or an unanswered commit. Absent means the
   *  range was never evaluated, which readers must fail closed on. */
  drift_ranges?: Record<string, boolean>
  environments?: DriftEnvironment[] | null
  release_summary?: null | {
    commits_since_tag: number
    drift_detected?: boolean
    head_sha: null | string
  }
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
        toLabelColor: b.label_color ?? null,
        toSlug: b.slug,
      })
    }
  }
  return pairs
}

// Same rule as `rangeNeedsAction`, over the tag..HEAD range: commits
// past the latest tag are suppressed only when the server positively
// answered `false` -- a `true` verdict or an unanswered commit both
// keep the range in the queue, and an absent field cannot hide it.
export function projectReleaseDrifted(
  project: Pick<DriftProject, 'release_summary'>,
): boolean {
  const s = project.release_summary
  if (!s?.head_sha) return false
  return s.commits_since_tag > 0 && s.drift_detected !== false
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
