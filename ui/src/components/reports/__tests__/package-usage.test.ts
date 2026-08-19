import { describe, expect, it } from 'vitest'

import {
  EMPTY_FACETS,
  facetsAreEmpty,
  filterUsageVersions,
  usageFacetOptions,
  type UsageFacets,
  usageRows,
} from '@/components/reports/package-usage'
import type { ComponentUsage, ComponentUsageVersion } from '@/types'

type Project = NonNullable<ComponentUsageVersion['projects']>[number]

function facets(overrides: Partial<Record<keyof UsageFacets, string[]>>) {
  const next: UsageFacets = {
    environment: new Set(),
    project_type: new Set(),
    team: new Set(),
  }
  for (const [key, values] of Object.entries(overrides)) {
    next[key as keyof UsageFacets] = new Set(values ?? [])
  }
  return next
}

function project(overrides: Partial<Project> = {}): Project {
  return {
    environments: ['Production'],
    id: 'proj-1',
    name: 'Billing API',
    project_types: ['HTTP API'],
    slug: 'billing-api',
    team: 'Platform',
    team_slug: 'platform',
    ...overrides,
  }
}

function usage(versions: ComponentUsageVersion[]): ComponentUsage {
  return {
    deployed_version_count: versions.length,
    description: null,
    ecosystem: 'npm',
    id: 'cmp-1',
    name: 'express',
    newest_deployed_version: versions[0]?.version ?? null,
    project_count: 1,
    purl_name: 'pkg:npm/express',
    status: null,
    status_at: null,
    status_by: null,
    version_count: versions.length,
    versions,
    vulnerable_project_count: 0,
  }
}

function version(
  overrides: Partial<ComponentUsageVersion> = {},
): ComponentUsageVersion {
  return {
    advisories: [],
    effective_status: null,
    environments: [
      { count: 1, label_color: null, name: 'Production', slug: 'production' },
    ],
    first_seen: null,
    id: 'crel-1',
    note_count: 0,
    project_count: 1,
    projects: [project()],
    status: null,
    status_at: null,
    status_by: null,
    status_inherited: false,
    version: '4.18.2',
    ...overrides,
  }
}

describe('usageRows', () => {
  it('emits one row per project and environment', () => {
    const rows = usageRows(
      usage([
        version({
          projects: [
            project({ environments: ['Production', 'Staging'] }),
            project({ id: 'proj-2', name: 'Auth API' }),
          ],
        }),
      ]),
    )
    expect(rows).toHaveLength(3)
    expect(rows.map((r) => r.environment)).toEqual([
      'Production',
      'Staging',
      'Production',
    ])
  })
})

describe('usageFacetOptions', () => {
  const rows = usageRows(
    usage([
      version({
        projects: [
          project({ environments: ['Production', 'Staging'] }),
          project({
            environments: ['Production'],
            id: 'proj-2',
            name: 'Auth API',
            project_types: ['Consumer'],
            team: 'Identity',
          }),
        ],
      }),
    ]),
  )

  it('counts each facet value across every deployment', () => {
    expect(usageFacetOptions(rows, EMPTY_FACETS, 'environment')).toEqual([
      { count: 2, label: 'Production', slug: 'Production' },
      { count: 1, label: 'Staging', slug: 'Staging' },
    ])
  })

  it('counts a facet against the others, not against itself', () => {
    // Picking Staging must not collapse the environment dropdown to
    // "Staging 1" — the reader is choosing what to switch to.
    const options = usageFacetOptions(
      rows,
      facets({ environment: ['Staging'] }),
      'environment',
    )
    expect(options).toEqual([
      { count: 2, label: 'Production', slug: 'Production' },
      { count: 1, label: 'Staging', slug: 'Staging' },
    ])
  })

  it('narrows the other facets by what is already selected', () => {
    expect(
      usageFacetOptions(rows, facets({ team: ['Identity'] }), 'project_type'),
    ).toEqual([
      { count: 1, label: 'Consumer', slug: 'Consumer' },
      { count: 0, label: 'HTTP API', slug: 'HTTP API' },
    ])
  })
})

describe('filterUsageVersions', () => {
  it('passes the payload through untouched with no facet selected', () => {
    const pkg = usage([version(), version({ id: 'crel-2', projects: [] })])
    expect(filterUsageVersions(pkg, EMPTY_FACETS)).toBe(pkg.versions)
  })

  it('drops a version nothing matching deploys', () => {
    const pkg = usage([
      version(),
      version({ id: 'crel-2', projects: [], version: '4.17.0' }),
    ])
    const kept = filterUsageVersions(pkg, facets({ team: ['Platform'] }))
    expect(kept.map((v) => v.version)).toEqual(['4.18.2'])
  })

  it('recounts environment chips against the surviving rows', () => {
    const pkg = usage([
      version({
        environments: [
          {
            count: 2,
            label_color: null,
            name: 'Production',
            slug: 'production',
          },
          { count: 1, label_color: null, name: 'Staging', slug: 'staging' },
        ],
        project_count: 2,
        projects: [
          project({ environments: ['Production', 'Staging'] }),
          project({ id: 'proj-2', name: 'Auth API' }),
        ],
      }),
    ])
    const [kept] = filterUsageVersions(pkg, facets({ team: ['Platform'] }))
    expect(kept.environments).toEqual([
      { count: 2, label_color: null, name: 'Production', slug: 'production' },
      { count: 1, label_color: null, name: 'Staging', slug: 'staging' },
    ])
    expect(kept.project_count).toBe(2)
  })

  it('drops the environments a facet excluded, chips included', () => {
    const pkg = usage([
      version({
        environments: [
          {
            count: 1,
            label_color: null,
            name: 'Production',
            slug: 'production',
          },
          { count: 1, label_color: null, name: 'Staging', slug: 'staging' },
        ],
        projects: [project({ environments: ['Production', 'Staging'] })],
      }),
    ])
    const [kept] = filterUsageVersions(
      pkg,
      facets({ environment: ['Staging'] }),
    )
    expect(kept.projects?.[0].environments).toEqual(['Staging'])
    expect(kept.environments).toEqual([
      { count: 1, label_color: null, name: 'Staging', slug: 'staging' },
    ])
  })

  it('keeps a project matching any one of its several types', () => {
    const pkg = usage([
      version({
        projects: [project({ project_types: ['HTTP API', 'Consumer'] })],
      }),
    ])
    expect(
      filterUsageVersions(pkg, facets({ project_type: ['Consumer'] })),
    ).toHaveLength(1)
  })
})

describe('facetsAreEmpty', () => {
  it('is true only with nothing selected anywhere', () => {
    expect(facetsAreEmpty(EMPTY_FACETS)).toBe(true)
    expect(facetsAreEmpty(facets({ team: ['Platform'] }))).toBe(false)
  })
})
