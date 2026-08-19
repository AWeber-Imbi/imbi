import type { ComponentUsage, ComponentUsageVersion } from '@/types'

/** The facets the filter bar above the table offers. */
export type UsageFacetKey = 'environment' | 'project_type' | 'team'

export type UsageFacets = Record<UsageFacetKey, Set<string>>

/**
 * One (version, project, environment) fact — the grain the facet
 * counts are taken at.
 *
 * A project deployed to three environments is three rows, so an
 * environment facet counts deployments rather than projects. That is
 * the number the reader is choosing between when they pick
 * "Production": how much of the table survives, not how many distinct
 * projects it mentions.
 */
export interface UsageRow {
  environment: string
  projectId: string
  projectTypes: string[]
  team: string
  versionId: string
}

export const EMPTY_FACETS: UsageFacets = {
  environment: new Set(),
  project_type: new Set(),
  team: new Set(),
}

export function facetsAreEmpty(facets: UsageFacets): boolean {
  return (
    facets.environment.size === 0 &&
    facets.project_type.size === 0 &&
    facets.team.size === 0
  )
}

/**
 * The table's versions with the facets applied.
 *
 * Environment chip counts are recomputed rather than carried over —
 * a chip reading "Production · 4" next to a table showing one project
 * is worse than no chip at all.
 *
 * With no facet selected the payload passes through untouched, so a
 * version nothing currently deploys still lists (it can be marked, and
 * the header's version count has to agree with the table). Under a
 * facet it drops: it matches nothing, and a row of blanks is not an
 * answer to "which projects run this in production".
 */
export function filterUsageVersions(
  pkg: ComponentUsage,
  facets: UsageFacets,
): ComponentUsageVersion[] {
  const versions = pkg.versions ?? []
  if (facetsAreEmpty(facets)) return versions
  return versions.flatMap((version) => {
    const projects = (version.projects ?? [])
      .map((project) => ({
        ...project,
        environments: (project.environments ?? []).filter((environment) =>
          matches(
            {
              environment,
              projectId: project.id,
              projectTypes: project.project_types ?? [],
              team: project.team ?? '',
              versionId: version.id,
            },
            facets,
          ),
        ),
      }))
      .filter((project) => project.environments.length > 0)
    if (projects.length === 0) return []
    const counts = new Map<string, number>()
    for (const project of projects) {
      for (const environment of project.environments) {
        counts.set(environment, (counts.get(environment) ?? 0) + 1)
      }
    }
    return [
      {
        ...version,
        environments: (version.environments ?? [])
          .filter((chip) => counts.has(chip.name))
          .map((chip) => ({ ...chip, count: counts.get(chip.name) ?? 0 })),
        project_count: projects.length,
        projects,
      },
    ]
  })
}

/** Options for one facet, counted against the other facets. */
export function usageFacetOptions(
  rows: UsageRow[],
  facets: UsageFacets,
  key: UsageFacetKey,
): { count: number; label: string; slug: string }[] {
  const counts = new Map<string, number>()
  for (const row of rows) {
    for (const value of facetValues(row, key)) {
      counts.set(value, (counts.get(value) ?? 0) + 0)
    }
  }
  for (const row of rows.filter((r) => matches(r, facets, key))) {
    for (const value of facetValues(row, key)) {
      counts.set(value, (counts.get(value) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, count]) => ({ count, label, slug: label }))
}

/** Flatten a package's versions into the per-deployment grain. */
export function usageRows(pkg: ComponentUsage): UsageRow[] {
  return (pkg.versions ?? []).flatMap((version) =>
    (version.projects ?? []).flatMap((project) =>
      (project.environments ?? []).map((environment) => ({
        environment,
        projectId: project.id,
        projectTypes: project.project_types ?? [],
        team: project.team ?? '',
        versionId: version.id,
      })),
    ),
  )
}

function facetValues(row: UsageRow, key: UsageFacetKey): string[] {
  if (key === 'environment') return [row.environment]
  if (key === 'team') return row.team ? [row.team] : []
  return row.projectTypes
}

/**
 * Does one row survive the selected facets?
 *
 * `ignore` drops a facet from the test, which is what makes each
 * dropdown's counts describe "how many rows if I also pick this"
 * rather than "how many rows I have now" — the latter would show every
 * unselected option in the open dropdown as zero.
 */
function matches(
  row: UsageRow,
  facets: UsageFacets,
  ignore?: UsageFacetKey,
): boolean {
  if (
    ignore !== 'environment' &&
    facets.environment.size > 0 &&
    !facets.environment.has(row.environment)
  ) {
    return false
  }
  if (ignore !== 'team' && facets.team.size > 0 && !facets.team.has(row.team)) {
    return false
  }
  // A project may carry several types, and matching any selected one
  // is enough — a "API + Consumer" project belongs to both facets.
  return (
    ignore === 'project_type' ||
    facets.project_type.size === 0 ||
    row.projectTypes.some((type) => facets.project_type.has(type))
  )
}
