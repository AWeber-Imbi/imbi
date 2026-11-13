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
      catalog(),
      {
        'imbi.gone': {},
        'imbi.list_projects': {},
        'zoekt.search': {},
      },
      none,
    )
    expect(views.map((v) => v.name)).toEqual(['Imbi', 'Not in the catalog'])
    expect(views[0].rows).toHaveLength(4)
    expect(views[1].rows).toEqual([
      {
        capability: null,
        description: null,
        key: 'imbi.gone',
        unavailable: true,
      },
      {
        capability: null,
        description: null,
        key: 'zoekt.search',
        unavailable: true,
      },
    ])
  })

  it('lists the built-in tools in their own group, first', () => {
    const views = groupViews(
      {
        ...catalog(),
        builtin_tools: [
          {
            capability: 'unknown',
            description: 'Start a subagent.',
            key: 'builtin.Agent',
            name: 'Agent',
          },
        ],
      },
      { 'builtin.Agent': {} },
      none,
    )
    expect(views.map((v) => v.name)).toEqual(['Built-in', 'Imbi'])
    expect(views[0].rows.map((r) => r.key)).toEqual(['builtin.Agent'])
    // Without built-in tools, no empty group.
    expect(groupViews(catalog(), {}, none).map((v) => v.name)).toEqual(['Imbi'])
  })

  it('filters by search, capability, and enabled', () => {
    const tools = { 'imbi.get_me': {} }
    const search = groupViews(catalog(), tools, {
      ...none,
      query: 'create',
    })
    expect(search[0].rows.map((r) => r.key)).toEqual(['imbi.create_project'])
    expect(groupViews(catalog(), tools, { ...none, query: 'nothing' })).toEqual(
      [],
    )
    // A failed catalog stays visible, so its error is not hidden.
    const failed = { ...catalog(), error: 'timeout' as const, tools: [] }
    expect(
      groupViews(failed, tools, { ...none, query: 'nothing' })[0].error,
    ).toBe('timeout')

    const destructive = groupViews(catalog(), tools, {
      ...none,
      capabilities: new Set(['destructive']),
    })
    expect(destructive.flatMap((v) => v.rows.map((r) => r.key))).toEqual([
      'imbi.delete_project',
    ])

    const enabled = groupViews(catalog(), tools, {
      ...none,
      enabledOnly: true,
    })
    expect(enabled.flatMap((v) => v.rows.map((r) => r.key))).toEqual([
      'imbi.get_me',
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
