import { describe, expect, it } from 'vitest'

import {
  applyFacets,
  EMPTY_FACETS,
  facetOptions,
  type Facets,
  matchesFinding,
  summarize,
} from '@/components/reports/problem-packages'
import type { ProblemPackageRow } from '@/types'

function facets(overrides: Partial<Record<keyof Facets, string[]>>): Facets {
  const next: Facets = {
    ecosystems: new Set(),
    environments: new Set(),
    findings: new Set(),
    projectTypes: new Set(),
    teams: new Set(),
  }
  for (const [key, values] of Object.entries(overrides)) {
    next[key as keyof Facets] = new Set(values ?? [])
  }
  return next
}

function row(overrides: Partial<ProblemPackageRow> = {}): ProblemPackageRow {
  return {
    advisories: [],
    component_id: 'cmp-1',
    component_name: 'express',
    component_release_id: 'crel-1',
    ecosystem: 'npm',
    environments: [
      { count: 1, label_color: null, name: 'Production', slug: 'production' },
    ],
    note_count: 0,
    project_id: 'proj-1',
    project_name: 'Billing API',
    project_slug: 'billing-api',
    project_types: ['HTTP API'],
    purl_name: 'pkg:npm/express',
    status: 'forbidden',
    status_inherited: false,
    team: 'Platform',
    team_slug: 'platform',
    version: '4.18.2',
    ...overrides,
  }
}

describe('applyFacets', () => {
  const rows = [
    row(),
    row({
      component_release_id: 'crel-2',
      ecosystem: 'pypi',
      project_id: 'proj-2',
      project_name: 'Auth API',
      purl_name: 'pkg:pypi/requests',
      status: 'deprecated',
      team: 'Identity',
    }),
  ]

  it('keeps every row when nothing is selected', () => {
    expect(applyFacets(rows, EMPTY_FACETS)).toHaveLength(2)
  })

  it('ANDs across facets', () => {
    const kept = applyFacets(
      rows,
      facets({ ecosystems: ['npm'], teams: ['Platform'] }),
    )
    expect(kept.map((r) => r.project_name)).toEqual(['Billing API'])
  })

  it('drops a row when the facets disagree', () => {
    expect(
      applyFacets(rows, facets({ ecosystems: ['npm'], teams: ['Identity'] })),
    ).toEqual([])
  })

  it('ORs within one facet', () => {
    expect(
      applyFacets(rows, facets({ ecosystems: ['npm', 'pypi'] })),
    ).toHaveLength(2)
  })

  it('ignores the excluded facet, so its own counts stay live', () => {
    const kept = applyFacets(
      rows,
      facets({ ecosystems: ['npm'] }),
      'ecosystems',
    )
    expect(kept).toHaveLength(2)
  })
})

describe('facetOptions', () => {
  const rows = [
    row(),
    row({
      component_release_id: 'crel-2',
      ecosystem: 'pypi',
      project_id: 'proj-2',
      status: 'deprecated',
      team: 'Identity',
    }),
  ]

  it('counts against the other facets, not its own', () => {
    const options = facetOptions(rows, facets({ ecosystems: ['npm'] }), 'teams')
    expect(options).toEqual([
      { count: 0, label: 'Identity', slug: 'Identity' },
      { count: 1, label: 'Platform', slug: 'Platform' },
    ])
  })

  it('keeps an option listed at zero once another facet excludes it', () => {
    const options = facetOptions(
      rows,
      facets({ ecosystems: ['npm'] }),
      'ecosystems',
    )
    // The ecosystem facet ignores its own selection, so both stay non-zero.
    expect(options.map((o) => o.slug)).toEqual(['npm', 'pypi'])
  })

  it('drops an option to zero rather than hiding it', () => {
    const options = facetOptions(
      rows,
      facets({ teams: ['Platform'] }),
      'ecosystems',
    )
    expect(options).toEqual([
      { count: 1, label: 'npm', slug: 'npm' },
      { count: 0, label: 'pypi', slug: 'pypi' },
    ])
  })

  it('offers all three findings even when none match', () => {
    const options = facetOptions([], EMPTY_FACETS, 'findings')
    expect(options.map((o) => o.slug)).toEqual([
      'forbidden',
      'deprecated',
      'advisory',
    ])
  })
})

describe('matchesFinding', () => {
  it('matches a status finding on the effective status', () => {
    expect(matchesFinding(row({ status: 'deprecated' }), 'deprecated')).toBe(
      true,
    )
    expect(matchesFinding(row({ status: 'deprecated' }), 'forbidden')).toBe(
      false,
    )
  })

  it('matches the advisory finding on a current row', () => {
    const withCve = row({
      advisories: [
        {
          created_at: null,
          created_by: null,
          cve_id: 'CVE-2025-1',
          title: null,
          url: 'https://example.com/1',
        },
      ],
      status: null,
    })
    expect(matchesFinding(withCve, 'advisory')).toBe(true)
    expect(matchesFinding(withCve, 'forbidden')).toBe(false)
  })
})

describe('summarize', () => {
  it('counts distinct projects, versions, and advisories', () => {
    const advisory = {
      created_at: null,
      created_by: null,
      cve_id: 'CVE-2025-1',
      title: null,
      url: 'https://example.com/1',
    }
    const stats = summarize([
      row({ advisories: [advisory] }),
      // Same version in a second project: one forbidden version, two
      // projects, and the shared advisory counted once.
      row({ advisories: [advisory], project_id: 'proj-2' }),
      row({
        component_release_id: 'crel-2',
        project_id: 'proj-3',
        status: 'deprecated',
      }),
    ])
    expect(stats).toEqual({
      advisories: 1,
      deprecated: 1,
      forbidden: 1,
      projects: 3,
    })
  })
})
