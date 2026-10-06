import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'

import { draftFromAgent, emptyDraft } from '../agentDraft'
import { AgentSaveError, saveAgent } from '../saveAgent'
import { agent, promptVersion } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAgent: vi.fn(),
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  setPromptLabel: vi.fn(),
  updateAgent: vi.fn(),
}))

const calls: string[] = []

function fail(name: string, error: unknown) {
  return () => {
    calls.push(name)
    return Promise.reject(error)
  }
}

function record(name: string, value: unknown) {
  return () => {
    calls.push(name)
    return Promise.resolve(value)
  }
}

describe('saveAgent', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    calls.length = 0
    vi.mocked(endpoints.createPromptVersion).mockImplementation(
      record('createPromptVersion', promptVersion({ n: 4 })),
    )
    vi.mocked(endpoints.createPrompt).mockImplementation(
      record('createPrompt', { latest_version: 1 }),
    )
    vi.mocked(endpoints.setPromptLabel).mockImplementation(
      record('setPromptLabel', {}),
    )
    vi.mocked(endpoints.updateAgent).mockImplementation(
      record('updateAgent', agent()),
    )
    vi.mocked(endpoints.createAgent).mockImplementation(
      record('createAgent', agent()),
    )
  })

  it('writes the prompt version, moves stable, then updates the agent', async () => {
    const existing = agent()
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.prompt.system = 'You fix bugs carefully.'

    const result = await saveAgent({
      baseline,
      draft,
      existing,
      orgSlug: 'acme',
    })

    expect(calls).toEqual([
      'createPromptVersion',
      'setPromptLabel',
      'updateAgent',
    ])
    expect(result.promptVersion).toBe(4)
    expect(endpoints.setPromptLabel).toHaveBeenCalledWith(
      'agents',
      'mender',
      'stable',
      4,
    )
    const [ns, slug, body] = vi.mocked(endpoints.createPromptVersion).mock
      .calls[0]
    expect([ns, slug]).toEqual(['agents', 'mender'])
    expect(body.system).toBe('You fix bugs carefully.')
    expect(body.model).toBe('claude-sonnet')
    // Content that the agent editor does not show is kept.
    expect(body.messages).toEqual(baseline.messages)
    expect(body.params).toEqual({
      max_tokens: 8192,
      stop_sequences: ['END'],
      temperature: 0.5,
      top_k: 40,
    })
    const [, agentSlug, doc] = vi.mocked(endpoints.updateAgent).mock.calls[0]
    expect(agentSlug).toBe('mender')
    expect(doc.prompt_ref).toBe('agents/mender@stable')
    expect(doc.prompt_version).toBe(4)
    expect(doc.version_summary).toBe('prompt v4')
  })

  it('stores the model parameters under the prompt params keys', async () => {
    const existing = agent()
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.prompt.params.thinking = { on: true, value: '16384' }
    draft.prompt.params.promptCaching = { on: true, value: '1h' }
    draft.prompt.params.topP = { on: true, value: '0.95' }
    draft.prompt.params.temperature = { on: false, value: '0.5' }

    await saveAgent({ baseline, draft, existing, orgSlug: 'acme' })

    const body = vi.mocked(endpoints.createPromptVersion).mock.calls[0][2]
    expect(body.params).toEqual({
      max_tokens: 8192,
      prompt_cache_ttl: '1h',
      stop_sequences: ['END'],
      thinking_budget: 16384,
      top_k: 40,
      top_p: 0.95,
    })
  })

  it('skips the prompt when only agent fields change', async () => {
    const existing = agent()
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.description = 'New description'

    await saveAgent({ baseline, draft, existing, orgSlug: 'acme' })

    expect(calls).toEqual(['updateAgent'])
    const doc = vi.mocked(endpoints.updateAgent).mock.calls[0][2]
    expect(doc.prompt_ref).toBe('agents/mender@stable')
    expect(doc.prompt_version).toBe(7)
    expect(doc.version_summary).toBe('Changed description')
  })

  it('records the loaded prompt version when the agent has none', async () => {
    const existing = agent({ prompt_version: null })
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.description = 'New description'

    await saveAgent({ baseline, draft, existing, orgSlug: 'acme' })

    const doc = vi.mocked(endpoints.updateAgent).mock.calls[0][2]
    expect(doc.prompt_version).toBe(2)
  })

  it('creates the prompt when it does not exist yet', async () => {
    vi.mocked(endpoints.createPromptVersion).mockImplementation(
      fail('createPromptVersion', new ApiError(404, 'Not Found')),
    )
    const draft = {
      ...emptyDraft(),
      name: 'Herald',
      slug: 'herald',
      team: 'platform',
    }
    draft.prompt.system = 'Announce releases.'

    await saveAgent({ baseline: null, draft, existing: null, orgSlug: 'acme' })

    expect(calls).toEqual([
      'createPromptVersion',
      'createPrompt',
      'setPromptLabel',
      'createAgent',
    ])
    const created = vi.mocked(endpoints.createPrompt).mock.calls[0][0]
    expect(created).toMatchObject({
      default_label: 'stable',
      kind: 'generative',
      namespace: 'agents',
      slug: 'acme.herald',
    })
    expect(endpoints.setPromptLabel).toHaveBeenCalledWith(
      'agents',
      'acme.herald',
      'stable',
      1,
    )
    const doc = vi.mocked(endpoints.createAgent).mock.calls[0][1]
    expect(doc).toMatchObject({
      enabled: true,
      name: 'Herald',
      prompt_ref: 'agents/acme.herald@stable',
      prompt_version: 1,
      slug: 'herald',
      team: 'platform',
    })
  })

  it('leaves prompt_ref unset for a new agent with no prompt', async () => {
    const draft = {
      ...emptyDraft(),
      name: 'Herald',
      slug: 'herald',
      team: 'platform',
    }
    await saveAgent({ baseline: null, draft, existing: null, orgSlug: 'acme' })
    expect(calls).toEqual(['createAgent'])
    expect(
      vi.mocked(endpoints.createAgent).mock.calls[0][1].prompt_ref,
    ).toBeNull()
  })

  it('keeps using the stored prompt after the agent slug changes', async () => {
    const existing = agent({ prompt_ref: 'agents/old-name@stable' })
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.prompt.model = 'claude-haiku'

    await saveAgent({ baseline, draft, existing, orgSlug: 'acme' })

    expect(vi.mocked(endpoints.createPromptVersion).mock.calls[0][1]).toBe(
      'old-name',
    )
    expect(vi.mocked(endpoints.updateAgent).mock.calls[0][2].prompt_ref).toBe(
      'agents/old-name@stable',
    )
  })

  it('stops before the agent write when the label move fails', async () => {
    vi.mocked(endpoints.setPromptLabel).mockImplementation(
      fail(
        'setPromptLabel',
        new ApiError(403, 'Forbidden', { detail: 'Missing prompt:promote' }),
      ),
    )
    const existing = agent()
    const baseline = promptVersion()
    const draft = draftFromAgent(existing, baseline)
    draft.prompt.system = 'Changed'

    const error = await saveAgent({
      baseline,
      draft,
      existing,
      orgSlug: 'acme',
    }).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(AgentSaveError)
    expect((error as AgentSaveError).step).toBe('prompt-label')
    expect((error as AgentSaveError).message).toBe(
      'Saved prompt version 4, but could not move the stable label to it: Missing prompt:promote. The agent was not saved.',
    )
    expect(calls).toEqual(['createPromptVersion', 'setPromptLabel'])
  })

  it('stops before the label move when the version write fails', async () => {
    vi.mocked(endpoints.createPromptVersion).mockImplementation(
      fail(
        'createPromptVersion',
        new ApiError(422, 'Unprocessable', {
          detail: "AI model 'x' is disabled",
        }),
      ),
    )
    const existing = agent()
    const draft = draftFromAgent(existing, promptVersion())
    draft.prompt.model = 'x'

    const error = await saveAgent({
      baseline: promptVersion(),
      draft,
      existing,
      orgSlug: 'acme',
    }).catch((e: unknown) => e)

    expect((error as AgentSaveError).step).toBe('prompt-version')
    expect((error as AgentSaveError).message).toContain('Nothing was saved')
    expect(calls).toEqual(['createPromptVersion'])
  })

  it('reports an agent write failure after the prompt was saved', async () => {
    vi.mocked(endpoints.updateAgent).mockImplementation(
      fail(
        'updateAgent',
        new ApiError(422, 'Unprocessable', { detail: "Team 'x' not found" }),
      ),
    )
    const existing = agent()
    const draft = draftFromAgent(existing, promptVersion())
    draft.prompt.system = 'Changed'

    const error = await saveAgent({
      baseline: promptVersion(),
      draft,
      existing,
      orgSlug: 'acme',
    }).catch((e: unknown) => e)

    expect((error as AgentSaveError).step).toBe('agent')
    expect((error as AgentSaveError).message).toBe(
      "Saved prompt version 4 and moved stable to it, but could not save the agent: Team 'x' not found.",
    )
  })
})
