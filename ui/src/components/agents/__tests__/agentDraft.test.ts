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
      githubAppBinding: '',
      kept: { approval_tools: [], denied_tools: [] },
      maxConcurrentTasks: '3',
      monthlyCostCap: '$400.00',
      plugins: [],
      requiredLabels: '',
      responseSla: '4h',
      secrets: '',
      taskBudget: '$5.00',
      taskTimeout: '30m',
    })
    const empty = {
      approval_tools: [],
      denied_tools: [],
      github_app_binding: null,
      plugins: [],
      secrets: [],
    }
    expect(settingsFromDraft(draft.settings)).toEqual({
      ...empty,
      max_concurrent_tasks: 3,
      monthly_cost_cap: '400.00',
      required_labels: [],
      response_sla: '4h',
      task_budget: '5.00',
      task_timeout_seconds: 1800,
    })
    expect(settingsFromDraft(emptyDraft().settings)).toEqual({
      ...empty,
      max_concurrent_tasks: null,
      monthly_cost_cap: null,
      required_labels: [],
      response_sla: null,
      task_budget: null,
      task_timeout_seconds: null,
    })
  })

  it('keeps the platform settings that the editor does not show', () => {
    const source = agent()
    source.settings = {
      ...source.settings,
      denied_tools: ['WebFetch'],
      github_app_binding: 'secret://gh/mender',
      permission_mode: 'plan',
      plugins: [{ marketplace: 'mp', plugin: 'lint', sha: 'a'.repeat(40) }],
      secrets: ['secret://ci/token'],
    }
    const draft = draftFromAgent(source, null)
    expect(draft.settings.secrets).toBe('secret://ci/token')
    const settings = settingsFromDraft(draft.settings)
    expect(settings.permission_mode).toBe('plan')
    expect(settings.denied_tools).toEqual(['WebFetch'])
    expect(settings.plugins).toEqual(source.settings.plugins)
    expect(settings.github_app_binding).toBe('secret://gh/mender')
  })

  it('checks the secret references', () => {
    const draft = draftFromAgent(agent(), null)
    draft.settings.secrets = 'secret://ci/token#value\n\nsecret://ci/x'
    expect(draftErrors(draft).secrets).toBeUndefined()
    draft.settings.secrets = 'ci/token'
    expect(draftErrors(draft).secrets).toBeTruthy()
    draft.settings.githubAppBinding = 'secret://gh/bot#field'
    expect(draftErrors(draft).githubAppBinding).toBeTruthy()
  })

  it('parses and checks the required runner labels', () => {
    const draft = emptyDraft()
    draft.settings.requiredLabels = ' gpu, general ,gpu,, '
    expect(settingsFromDraft(draft.settings).required_labels).toEqual([
      'general',
      'gpu',
    ])
    draft.settings.requiredLabels = 'GPU'
    expect(draftErrors(draft).requiredLabels).toBeTruthy()
  })

  it('keeps a task budget below one cent', () => {
    const base = agent()
    const draft = draftFromAgent(
      { ...base, settings: { ...base.settings, task_budget: '0.004' } },
      null,
    )
    expect(draft.settings.taskBudget).toBe('$0.004')
    expect(settingsFromDraft(draft.settings).task_budget).toBe('0.004')
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
    draft.settings.taskBudget = 'lots'
    expect(draftErrors(draft)).toEqual({
      'param.maxTokens': 'Enter a whole number above 0',
      taskBudget: 'Enter an amount, for example $5',
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
