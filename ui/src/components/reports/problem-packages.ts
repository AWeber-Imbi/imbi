import { statusLabel } from '@/components/packages/status'
import type { FilterOption } from '@/components/ui/filter-popover'
import { downloadCsv } from '@/lib/csv'
import type { ProblemPackageRow } from '@/types'

/** The five facets, each a Set of selected slugs. */
export type FacetKey =
  | 'ecosystems'
  | 'environments'
  | 'findings'
  | 'projectTypes'
  | 'teams'

export type Facets = Record<FacetKey, Set<string>>

/**
 * A finding is what makes a row worth showing. The three are not
 * mutually exclusive — a forbidden version with a CVE matches both
 * `forbidden` and `advisory` — so the facet is a genuine multi-select.
 */
const FINDING_OPTIONS: { label: string; slug: string }[] = [
  { label: 'Forbidden', slug: 'forbidden' },
  { label: 'Deprecated', slug: 'deprecated' },
  { label: 'Known advisory', slug: 'advisory' },
]

export const EMPTY_FACETS: Facets = {
  ecosystems: new Set(),
  environments: new Set(),
  findings: new Set(),
  projectTypes: new Set(),
  teams: new Set(),
}

/** Rows matching every facet except `except`, for cross-filtered counts. */
export function applyFacets(
  rows: ProblemPackageRow[],
  facets: Facets,
  except?: FacetKey,
): ProblemPackageRow[] {
  return rows.filter((row) =>
    (Object.keys(facets) as FacetKey[]).every(
      (key) => key === except || matchesFacet(row, key, facets[key]),
    ),
  )
}

export function exportCsv(rows: ProblemPackageRow[]): void {
  downloadCsv(
    'problem-packages.csv',
    [
      'Project',
      'Team',
      'Project Types',
      'Package',
      'Version',
      'Status',
      'Advisories',
      'Environments',
      'Notes',
    ],
    rows.map((row) => [
      row.project_name,
      row.team ?? '',
      (row.project_types ?? []).join('; '),
      row.purl_name,
      row.version,
      row.status ? statusLabel(row.status) : 'Current',
      (row.advisories ?? []).map((a) => a.cve_id).join('; '),
      (row.environments ?? []).map((e) => e.name).join('; '),
      row.note_count,
    ]),
  )
}

/** Options for one facet, counted against the other facets' selections. */
export function facetOptions(
  rows: ProblemPackageRow[],
  facets: Facets,
  key: FacetKey,
): FilterOption[] {
  const scope = applyFacets(rows, facets, key)
  if (key === 'findings') {
    return FINDING_OPTIONS.map((option) => ({
      count: scope.filter((row) => matchesFinding(row, option.slug)).length,
      label: option.label,
      slug: option.slug,
    }))
  }
  const counts = new Map<string, number>()
  for (const row of rows) {
    for (const value of facetValues(row, key)) {
      if (!counts.has(value)) counts.set(value, 0)
    }
  }
  for (const row of scope) {
    for (const value of facetValues(row, key)) {
      counts.set(value, (counts.get(value) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([slug, count]) => ({ count, label: slug, slug }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

export function matchesFinding(
  row: ProblemPackageRow,
  finding: string,
): boolean {
  if (finding === 'advisory') return (row.advisories ?? []).length > 0
  return row.status === finding
}

export function summarize(rows: ProblemPackageRow[]) {
  return {
    advisories: new Set(
      rows.flatMap((row) => (row.advisories ?? []).map((a) => a.cve_id)),
    ).size,
    deprecated: new Set(
      rows
        .filter((row) => row.status === 'deprecated')
        .map((row) => row.component_release_id),
    ).size,
    forbidden: new Set(
      rows
        .filter((row) => row.status === 'forbidden')
        .map((row) => row.component_release_id),
    ).size,
    projects: new Set(rows.map((row) => row.project_id)).size,
  }
}

/** The values of `row` for one facet; a row can carry several. */
function facetValues(row: ProblemPackageRow, key: FacetKey): string[] {
  switch (key) {
    case 'ecosystems':
      return [row.ecosystem]
    case 'environments':
      return (row.environments ?? []).map((env) => env.name)
    case 'findings':
      return FINDING_OPTIONS.map((o) => o.slug).filter((slug) =>
        matchesFinding(row, slug),
      )
    case 'projectTypes':
      return row.project_types ?? []
    case 'teams':
      return row.team ? [row.team] : []
  }
}

function matchesFacet(
  row: ProblemPackageRow,
  key: FacetKey,
  selected: Set<string>,
): boolean {
  if (selected.size === 0) return true
  return facetValues(row, key).some((value) => selected.has(value))
}
