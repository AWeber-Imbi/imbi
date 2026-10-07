import { describe, expect, it } from 'vitest'

import {
  draftErrors,
  draftFromAgent,
  duplicateDraft,
  emptyDraft,
  formatDuration,
  isPromptChanged,
  normalizeTools,
  parseDuration,
  parseMoney,
  settingsFromDraft,
  versionSummary,
} from '../agentDraft'
import { agent, promptVersion } from './fixtures'

describe('agentDraft', () => {
  it('reads the prompt params into switched-on controls', () => {
    const draft = draftFromAgent(agent(), promptVersion())
    expect(draft.prompt.params.maxTokens).toEqual({ on: true, value: '8192' })
    expect(draft.prompt.params.topK).toEqual({ on: true, value: '40' })
    expect(draft.prompt.params.topP.on).toBe(false)
    expect(draft.prompt.model).toBe('claude-sonnet')
    expect(isPromptChanged(draft.prompt, promptVersion())).toBe(false)
  })

  it('treats a switched-off control as a change', () => {
    const draft = draftFromAgent(agent(), promptVersion())
    draft.prompt.params.topK = { on: false, value: '40' }
    expect(isPromptChanged(draft.prompt, promptVersion())).toBe(true)
  })

  it('round-trips the settings', () => {
    const draft = draftFromAgent(agent(), null)
    expect(draft.settings).toEqual({
      maxConcurrentTasks: '3',
      monthlyCostCap: '$400.00',
      responseSla: '4h',
      taskTimeout: '30m',
    })
    expect(settingsFromDraft(draft.settings)).toEqual({
      max_concurrent_tasks: 3,
      monthly_cost_cap: '400.00',
      response_sla: '4h',
      task_timeout_seconds: 1800,
    })
    expect(settingsFromDraft(emptyDraft().settings)).toEqual({
      max_concurrent_tasks: null,
      monthly_cost_cap: null,
      response_sla: null,
      task_timeout_seconds: null,
    })
  })

  it('parses durations and money', () => {
    expect(parseDuration('30m')).toBe(1800)
    expect(parseDuration('2h')).toBe(7200)
    expect(parseDuration('45')).toBe(2700)
    expect(parseDuration('soon')).toBeNull()
    expect(formatDuration(5400)).toBe('90m')
    expect(formatDuration(86400)).toBe('1d')
    expect(parseMoney('$1,200.50')).toBe('1200.50')
    expect(parseMoney('lots')).toBeNull()
  })

  it('names a duplicate "<name> copy"', () => {
    const draft = duplicateDraft(agent(), promptVersion())
    expect(draft.name).toBe('Mender copy')
    expect(draft.slug).toBe('mender-copy')
    expect(draft.prompt.system).toBe('You fix bugs.')
  })

  it('requires a name and an owner team', () => {
    expect(draftErrors(emptyDraft())).toEqual({
      name: 'Agent name is required',
      team: 'Owner team is required',
    })
    const draft = draftFromAgent(agent(), promptVersion())
    draft.prompt.params.maxTokens = { on: true, value: 'many' }
    draft.settings.taskTimeout = 'later'
    expect(draftErrors(draft)).toEqual({
      'param.maxTokens': 'Enter a whole number above 0',
      taskTimeout: 'Enter a duration, for example 30m or 2h',
    })
  })

  it('maps tools to the draft and names a tool change', () => {
    const tools = {
      'imbi.update_project': {
        approval: true,
        environments: ['staging', 'production'],
        rate_limit: { count: 6, per: 'hour' as const },
      },
    }
    const existing = agent({ tools })
    const draft = draftFromAgent(existing, null)
    expect(draft.tools).toEqual(tools)
    expect(emptyDraft().tools).toEqual({})
    expect(duplicateDraft(existing, null).tools).toEqual(tools)
    expect(versionSummary(existing, draft, null)).toBe('Saved')

    // The same tools in another order are not a change.
    draft.tools = {
      'imbi.update_project': {
        approval: true,
        environments: ['production', 'staging'],
        rate_limit: { count: 6, per: 'hour' },
      },
    }
    expect(versionSummary(existing, draft, null)).toBe('Saved')

    draft.tools = { ...draft.tools, 'github.read_file': { approval: false } }
    expect(versionSummary(existing, draft, null)).toBe('Changed tools')
    draft.name = 'Fixer'
    expect(versionSummary(existing, draft, 2)).toBe(
      'Changed name, tools; prompt v2',
    )
  })

  it('maps subagents to the draft and names a subagent change', () => {
    const existing = agent({
      subagents: [
        {
          agent_id: 'agt-2',
          icon: null,
          instructions: 'Only post summaries.',
          name: 'Herald',
          slug: 'herald',
          tool_count: 4,
          version: 5,
        },
      ],
    })
    const draft = draftFromAgent(existing, null)
    expect(draft.subagents).toEqual([
      { agent_id: 'agt-2', instructions: 'Only post summaries.' },
    ])
    expect(emptyDraft().subagents).toEqual([])
    expect(duplicateDraft(existing, null).subagents).toEqual(draft.subagents)
    expect(versionSummary(existing, draft, null)).toBe('Saved')

    draft.subagents = [{ agent_id: 'agt-2', instructions: '' }]
    expect(versionSummary(existing, draft, null)).toBe('Changed subagents')
    draft.subagents = [
      { agent_id: 'agt-2', instructions: 'Only post summaries.' },
      { agent_id: 'agt-3', instructions: '' },
    ]
    expect(versionSummary(existing, draft, null)).toBe('Changed subagents')
  })

  it('normalizes tools to the stored form', () => {
    expect(
      normalizeTools({
        'a.tool': { approval: true },
        'z.tool': { approval: false, environments: ['b', 'a', 'b'] },
      }),
    ).toEqual({
      'a.tool': { approval: true, environments: null, rate_limit: null },
      'z.tool': {
        approval: false,
        environments: ['a', 'b'],
        rate_limit: null,
      },
    })
  })
})
