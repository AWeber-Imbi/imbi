import { describe, expect, it } from 'vitest'

import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
  ReleaseHistoryEntry,
} from '@/types'

import {
  buildPipeline,
  commitRange,
  compareTags,
  defaultStageSlug,
} from './pipeline'

const env = (slug: string, sortOrder: number): Environment =>
  ({
    can_deploy: true,
    can_promote: false,
    id: slug,
    label_color: '#5A89C9',
    name: slug[0].toUpperCase() + slug.slice(1),
    slug,
    sort_order: sortOrder,
  }) as unknown as Environment

const currentRelease = (
  slug: string,
  committish: string,
  tag: null | string,
): CurrentReleaseEnvironment => ({
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: slug, slug },
  external_run_url: null,
  last_event_at: '2026-06-01T00:00:00Z',
  release: {
    committish,
    created_at: '2026-06-01T00:00:00Z',
    created_by: 'gavin',
    id: `${slug}-release`,
    links: [],
    project_id: 'p1',
    tag,
    title: tag ?? committish,
  },
})

const entry = (tag: string, sha: string): ReleaseHistoryEntry => ({
  ci_status: 'pass',
  notes_markdown: `notes for ${tag}`,
  published_at: '2026-06-01T00:00:00Z',
  sha,
  short_sha: sha.slice(0, 7),
  tag,
})

const commit = (sha: string, message: string): RecentCommit => ({
  authored_at: '2026-06-01T00:00:00Z',
  ci_status: 'pass',
  message,
  sha,
  short_sha: sha.slice(0, 7),
})

const ENVS = [env('testing', 1), env('staging', 2), env('production', 3)]

// Newest (highest semver) first, mirroring /deployments/release-history.
const HISTORY = [
  entry('v6.5.2', 'ccc333ccc333'),
  entry('v6.5.1', 'bbb222bbb222'),
  entry('v6.5.0', 'aaa111aaa111'),
  entry('v6.4.0', '000999000999'),
]

// Newest-first synced default-branch history.
const COMMITS = [
  commit('fff666fff666', 'newest unreleased'),
  commit('eee555eee555', 'also unreleased'),
  commit('ddd444ddd444', 'deployed to testing'),
  commit('ccc333ccc333', 'release v6.5.2'),
  commit('bbb222bbb222', 'release v6.5.1'),
  commit('aaa111aaa111', 'release v6.5.0'),
]

const CURRENT = [
  currentRelease('testing', 'ddd444ddd444', null),
  currentRelease('staging', 'ccc333ccc333', 'v6.5.2'),
  currentRelease('production', 'aaa111aaa111', 'v6.5.0'),
]

describe('buildPipeline', () => {
  const stages = buildPipeline(ENVS, CURRENT, HISTORY, COMMITS)

  it('derives stage kinds from upstream data, not position names', () => {
    expect(stages.map((s) => s.kind)).toEqual(['commit', 'promote', 'release'])
  })

  it('computes pending commits for promote stages from the synced history', () => {
    const staging = stages[1]
    // Testing runs ddd444; staging's release was cut at ccc333 — one
    // commit is waiting, and the unreleased commits beyond testing are
    // not offered.
    expect(staging.pendingCommits.map((c) => c.sha)).toEqual(['ddd444ddd444'])
  })

  it('computes pending releases between the env and its upstream', () => {
    const production = stages[2]
    expect(production.pendingReleases.map((r) => r.tag)).toEqual([
      'v6.5.2',
      'v6.5.1',
    ])
  })

  it('treats an env with no release as pending everything up to upstream', () => {
    const noProd = CURRENT.filter((c) => c.environment.slug !== 'production')
    const result = buildPipeline(ENVS, noProd, HISTORY, COMMITS)
    expect(result[2].pendingReleases.map((r) => r.tag)).toEqual([
      'v6.5.2',
      'v6.5.1',
      'v6.5.0',
      'v6.4.0',
    ])
  })

  it('returns no pending releases when the env matches its upstream', () => {
    const synced = [
      currentRelease('testing', 'ddd444ddd444', null),
      currentRelease('staging', 'ccc333ccc333', 'v6.5.2'),
      currentRelease('production', 'ccc333ccc333', 'v6.5.2'),
    ]
    const result = buildPipeline(ENVS, synced, HISTORY, COMMITS)
    expect(result[2].pendingReleases).toEqual([])
  })

  it('offers a divergent upstream release even when the env ranks ahead', () => {
    // Production runs 2.101.0 while staging runs 1.102.3 — different
    // releases, so staging's stays deployable (the composer case).
    const history = [entry('2.101.0', 'ccc333ccc333'), ...HISTORY]
    const divergent = [
      currentRelease('testing', 'ddd444ddd444', null),
      currentRelease('staging', 'aaa111aaa111', 'v6.5.0'),
      currentRelease('production', 'ccc333ccc333', '2.101.0'),
    ]
    const result = buildPipeline(ENVS, divergent, history, COMMITS)
    expect(result[2].pendingReleases.map((r) => r.tag)).toEqual(['v6.5.0'])
  })

  it('offers the upstream release when its tag is missing from history', () => {
    const divergent = [
      currentRelease('testing', 'ddd444ddd444', null),
      currentRelease('staging', '123abc123abc', 'v7.0.0'),
      currentRelease('production', 'ccc333ccc333', 'v6.5.2'),
    ]
    const result = buildPipeline(ENVS, divergent, HISTORY, COMMITS)
    expect(result[2].pendingReleases.map((r) => r.tag)).toEqual(['v7.0.0'])
    expect(result[2].pendingReleases[0].sha).toBe('123abc123abc')
  })

  it('collects rollback targets older than the current tag', () => {
    const production = stages[2]
    expect(production.rollbackTargets.map((r) => r.tag)).toEqual(['v6.4.0'])
    const staging = stages[1]
    expect(staging.rollbackTargets.map((r) => r.tag)).toEqual([
      'v6.5.1',
      'v6.5.0',
      'v6.4.0',
    ])
  })

  it('falls back to semver ranking when the current tag is unsynced', () => {
    // 2.101.0 is not in HISTORY; everything older still ranks below it.
    const unsynced = [currentRelease('production', '999000999000', '2.101.0')]
    const result = buildPipeline(ENVS, unsynced, HISTORY, COMMITS)
    expect(result[2].rollbackTargets.map((r) => r.tag)).toEqual([])
    const olderLine = [currentRelease('production', '999000999000', 'v6.5.3')]
    const result2 = buildPipeline(ENVS, olderLine, HISTORY, COMMITS)
    expect(result2[2].rollbackTargets.map((r) => r.tag)).toEqual([
      'v6.5.2',
      'v6.5.1',
      'v6.5.0',
      'v6.4.0',
    ])
  })

  it('treats a tagged upstream as release-kind even mid-train', () => {
    const envs = [...ENVS, env('dr', 4)]
    const current = [...CURRENT, currentRelease('dr', '000999000999', 'v6.4.0')]
    const result = buildPipeline(envs, current, HISTORY, COMMITS)
    expect(result[3].kind).toBe('release')
    expect(result[3].pendingReleases.map((r) => r.tag)).toEqual(['v6.5.0'])
  })
})

describe('commitRange', () => {
  it('slices from head (inclusive) down to base (exclusive)', () => {
    expect(
      commitRange(COMMITS, 'ddd444ddd444', 'bbb222bbb222').map((c) => c.sha),
    ).toEqual(['ddd444ddd444', 'ccc333ccc333'])
  })

  it('matches sha prefixes in either direction', () => {
    expect(
      commitRange(COMMITS, 'ddd444d', 'ccc333c').map((c) => c.sha),
    ).toEqual(['ddd444ddd444'])
  })

  it('returns the window remainder when the base is older than it', () => {
    expect(
      commitRange(COMMITS, 'bbb222bbb222', '777zzz777zzz').map((c) => c.sha),
    ).toEqual(['bbb222bbb222', 'aaa111aaa111'])
  })

  it('returns nothing when the head is unknown or not ahead', () => {
    expect(commitRange(COMMITS, '777zzz777zzz', 'aaa111aaa111')).toEqual([])
    expect(commitRange(COMMITS, 'aaa111aaa111', 'aaa111aaa111')).toEqual([])
    expect(commitRange(COMMITS, 'aaa111aaa111', 'ccc333ccc333')).toEqual([])
  })
})

describe('compareTags', () => {
  it('orders semver tags and tolerates a leading v', () => {
    expect(compareTags('1.102.3', '2.101.0')).toBeLessThan(0)
    expect(compareTags('v6.5.2', '6.5.2')).toBe(0)
    expect(compareTags('not-semver', '1.0.0')).toBeNull()
  })
})

describe('defaultStageSlug', () => {
  it('selects the first rendered environment (highest sort order)', () => {
    const stages = buildPipeline(ENVS, CURRENT, HISTORY, COMMITS)
    expect(defaultStageSlug(stages)).toBe('production')
    expect(defaultStageSlug([])).toBeNull()
  })
})
