// Environment drift: whether what's deployed in one environment differs
// from the next one down the pipeline. Shared by the projects list (drift
// filters + badges) and the project detail tabs so both agree on the rule.

export interface DriftEnvironment {
  label_color?: null | string
  name: string
  slug: string
  sort_order?: null | number
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

export function computeDriftPairs(
  environments: DriftEnvironment[],
  releases: Record<string, { committish?: null | string; tag?: null | string }>,
): DriftPair[] {
  const sorted = [...environments].sort(
    (a, b) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name),
  )
  const pairs: DriftPair[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i]
    const b = sorted[i + 1]
    const ra = releases[a.slug]
    const rb = releases[b.slug]
    const aTag = ra?.tag ?? null
    const bTag = rb?.tag ?? null
    const aSha = ra?.committish ?? null
    const bSha = rb?.committish ?? null
    // When both envs have a SHA, compare them directly so that a tag-only
    // difference on identical commits does not register as drift. Otherwise
    // fall back to tag-or-SHA equality.
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
  return pairs
}
