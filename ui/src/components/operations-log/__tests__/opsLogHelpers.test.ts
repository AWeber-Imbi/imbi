import { describe, expect, it } from 'vitest'

import type { OperationsLogRecord } from '@/types'

import { groupReleases } from '../opsLogHelpers'

const SHA = 'c67213d'

function makeEntry(
  overrides: Partial<OperationsLogRecord> = {},
): OperationsLogRecord {
  return {
    description: payload('deploy'),
    entry_type: 'Deployed',
    environment_slug: 'production',
    id: 'opslog-1',
    occurred_at: '2026-07-27T12:25:28.139Z',
    plugin_slug: 'github',
    project_id: 'proj-1',
    project_slug: 'webform',
    recorded_at: '2026-07-27T12:25:28.139Z',
    recorded_by: 'dang@aweber.com',
    version: '1.29.0',
    ...overrides,
  }
}

function payload(action: string, sha: null | string = SHA): string {
  return JSON.stringify({
    action,
    commit_sha: sha,
    from_environment: action === 'promote' ? 'testing' : null,
    plugin_slug: 'github',
  })
}

describe('groupReleases', () => {
  it('groups a promote and a deploy of the same version into one train', () => {
    const items = groupReleases([
      makeEntry(),
      makeEntry({
        description: payload('promote'),
        environment_slug: 'staging',
        id: 'opslog-2',
        occurred_at: '2026-07-27T12:02:34.325Z',
      }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0]!.kind).toBe('release')
    if (items[0]!.kind !== 'release') return
    const group = items[0]!.group
    expect(group.version).toBe('1.29.0')
    expect(group.latestEntry.id).toBe('opslog-1')
    expect(group.stops.map((s) => s.environment_slug)).toEqual([
      'production',
      'staging',
    ])
  })

  it('joins an untagged deploy to the train by committish', () => {
    const items = groupReleases([
      makeEntry(),
      makeEntry({
        description: payload('promote'),
        environment_slug: 'staging',
        id: 'staging',
        occurred_at: '2026-07-27T12:02:34.325Z',
      }),
      // Testing shipped straight off the commit: no tag, so the sha is
      // both the version and the committish.
      makeEntry({
        environment_slug: 'testing',
        id: 'testing',
        occurred_at: '2026-07-27T11:40:00.000Z',
        version: SHA,
      }),
    ])
    expect(items).toHaveLength(1)
    if (items[0]!.kind !== 'release') return
    expect(items[0]!.group.version).toBe('1.29.0')
    expect(items[0]!.group.stops.map((s) => s.environment_slug)).toEqual([
      'production',
      'staging',
      'testing',
    ])
  })

  it('fuses trains that each knew only one identity', () => {
    const items = groupReleases([
      // Legacy row: tag but no recorded committish.
      makeEntry({ description: payload('deploy', null), id: 'prod-no-sha' }),
      makeEntry({
        environment_slug: 'testing',
        id: 'testing',
        occurred_at: '2026-07-27T11:40:00.000Z',
        version: SHA,
      }),
      // Knows both, so it fuses the two trains above.
      makeEntry({
        description: payload('promote'),
        environment_slug: 'staging',
        id: 'staging',
        occurred_at: '2026-07-27T12:02:34.325Z',
      }),
    ])
    expect(items).toHaveLength(1)
    if (items[0]!.kind !== 'release') return
    const group = items[0]!.group
    expect(group.version).toBe('1.29.0')
    expect(group.latestEntry.id).toBe('prod-no-sha')
    expect(group.stops.map((s) => s.environment_slug).sort()).toEqual([
      'production',
      'staging',
      'testing',
    ])
  })

  it('keeps the fused train in the newest slot of the two it merged', () => {
    const items = groupReleases([
      // Legacy row: tag but no recorded committish. Newest, so the train
      // it opens is the slot the fused train has to keep.
      makeEntry({ description: payload('deploy', null), id: 'prod-no-sha' }),
      // Ungrouped row sitting between the two trains. If the merge kept
      // the absorbed (older) train's slot instead, the fused train would
      // sort below this restart.
      makeEntry({
        entry_type: 'Restarted',
        id: 'restart',
        occurred_at: '2026-07-27T12:10:00.000Z',
        version: null,
      }),
      makeEntry({
        environment_slug: 'testing',
        id: 'testing',
        occurred_at: '2026-07-27T11:40:00.000Z',
        version: SHA,
      }),
      // Knows both identities, so it fuses the two trains above.
      makeEntry({
        description: payload('promote'),
        environment_slug: 'staging',
        id: 'staging',
        occurred_at: '2026-07-27T12:02:34.325Z',
      }),
    ])
    expect(items.map((i) => i.kind)).toEqual(['release', 'single'])
    if (items[0]!.kind !== 'release') return
    expect(items[0]!.group.latestEntry.id).toBe('prod-no-sha')
    expect(items[0]!.group.stops.map((s) => s.environment_slug).sort()).toEqual(
      ['production', 'staging', 'testing'],
    )
  })

  it('keeps a tag as the display version over a bare committish', () => {
    const items = groupReleases([
      makeEntry({
        environment_slug: 'testing',
        id: 'testing',
        occurred_at: '2026-07-27T12:40:00.000Z',
        version: SHA,
      }),
      makeEntry({ id: 'prod', occurred_at: '2026-07-27T12:25:28.139Z' }),
    ])
    expect(items).toHaveLength(1)
    if (items[0]!.kind !== 'release') return
    expect(items[0]!.group.version).toBe('1.29.0')
    expect(items[0]!.group.latestEntry.id).toBe('testing')
  })

  it('keeps different versions in separate groups', () => {
    const items = groupReleases([
      makeEntry(),
      makeEntry({
        description: payload('deploy', 'deadbee'),
        id: 'opslog-3',
        occurred_at: '2026-07-21T15:25:27.903Z',
        version: '1.28.2',
      }),
    ])
    expect(items).toHaveLength(2)
    expect(
      items.map((i) => (i.kind === 'release' ? i.group.version : null)),
    ).toEqual(['1.29.0', '1.28.2'])
  })

  it('keeps the earliest deploy into each environment as the stop', () => {
    const items = groupReleases([
      makeEntry({ id: 'later', occurred_at: '2026-06-16T19:12:09.163Z' }),
      makeEntry({ id: 'earlier', occurred_at: '2026-06-16T11:46:06.501Z' }),
    ])
    expect(items).toHaveLength(1)
    if (items[0]!.kind !== 'release') return
    expect(items[0]!.group.stops[0]!.entry.id).toBe('earlier')
    expect(items[0]!.group.latestEntry.id).toBe('later')
  })

  it('leaves non-deploy entries and versionless deploys ungrouped', () => {
    const items = groupReleases([
      makeEntry({ entry_type: 'Configured', id: 'cfg', version: null }),
      makeEntry({ id: 'no-version', version: null }),
    ])
    expect(items.map((i) => i.kind)).toEqual(['single', 'single'])
  })

  it('does not group the same version across projects', () => {
    const items = groupReleases([
      makeEntry(),
      makeEntry({ id: 'other', project_slug: 'messages-client' }),
    ])
    expect(items).toHaveLength(2)
  })
})
