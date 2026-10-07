import { describe, expect, it } from 'vitest'

import {
  formatRateLimit,
  groupViews,
  serverOf,
  setTools,
  toggleEnvironment,
  type ToolFilters,
} from '../agentTools'
import { catalog } from './fixtures'

const none: ToolFilters = {
  capabilities: new Set(),
  enabledOnly: false,
  query: '',
}

describe('agentTools', () => {
  it('reads the server of a tool key', () => {
    expect(serverOf('github.read_file')).toBe('github')
    expect(serverOf('imbi.a.b')).toBe('imbi')
  })

  it('shows tools that the catalog does not list as unavailable', () => {
    const views = groupViews(
      catalog().groups,
      {
        'gone.old_tool': {},
        'imbi.list_projects': {},
        'sentry.resolve_issue': {},
      },
      none,
    )
    expect(views.map((v) => v.name)).toEqual([
      'Imbi',
      'GitHub',
      'Sentry',
      'Not in the catalog',
    ])
    const sentry = views[2]
    expect(sentry.error).toBe('timeout')
    expect(sentry.rows).toEqual([
      {
        capability: null,
        description: null,
        key: 'sentry.resolve_issue',
        unavailable: true,
      },
    ])
    expect(views[3].rows.map((r) => r.key)).toEqual(['gone.old_tool'])
  })

  it('filters by search, capability, and enabled', () => {
    const tools = { 'github.read_file': {} }
    const search = groupViews(catalog().groups, tools, {
      ...none,
      query: 'pull',
    })
    // A failed server stays visible, so its error is not hidden.
    expect(search.map((v) => v.slug)).toEqual(['github', 'sentry'])
    expect(search[0].rows.map((r) => r.key)).toEqual([
      'github.create_pull_request',
    ])

    const destructive = groupViews(catalog().groups, tools, {
      ...none,
      capabilities: new Set(['destructive']),
    })
    expect(destructive.flatMap((v) => v.rows.map((r) => r.key))).toEqual([
      'imbi.delete_project',
    ])

    const enabled = groupViews(catalog().groups, tools, {
      ...none,
      enabledOnly: true,
    })
    expect(enabled.flatMap((v) => v.rows.map((r) => r.key))).toEqual([
      'github.read_file',
    ])
  })

  it('switches tools on with defaults and keeps a stored config', () => {
    const tools = { 'github.read_file': { approval: true } }
    expect(
      setTools(tools, ['github.read_file', 'github.create_pull_request'], true),
    ).toEqual({
      'github.create_pull_request': {
        approval: false,
        environments: null,
        rate_limit: null,
      },
      'github.read_file': { approval: true },
    })
    expect(setTools(tools, ['github.read_file'], false)).toEqual({})
  })

  it('toggles environments; all allowed is null', () => {
    const all = ['production', 'staging', 'testing']
    const blocked = toggleEnvironment({}, 'production', all)
    expect(blocked.environments).toEqual(['staging', 'testing'])
    expect(toggleEnvironment(blocked, 'production', all).environments).toBe(
      null,
    )
    // The last environment cannot be blocked.
    const one = { environments: ['staging'] }
    expect(toggleEnvironment(one, 'staging', all)).toBe(one)
  })

  it('formats rate limits', () => {
    expect(formatRateLimit({})).toBe('No limit')
    expect(formatRateLimit({ rate_limit: { count: 6, per: 'hour' } })).toBe(
      '6 / hr',
    )
  })
})
