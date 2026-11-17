import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import type { Prompt, PromptResolution, PromptVersion } from '@/types'

import { saveWorkflow, type StepPrompt } from '../analysisPrompt'
import type { Workflow, WorkflowWrite } from '../types'
import { node, workflow } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  createWorkflow: vi.fn(),
  resolvePrompt: vi.fn(),
  updateWorkflow: vi.fn(),
}))

const PROMPT: StepPrompt = {
  max_tokens: 500,
  model: 'claude',
  system: 'Be brief.',
  temperature: null,
  user: 'Summarize {{ log }}',
}

const VERSION_BODY = {
  messages: [{ content: 'Summarize {{ log }}', role: 'user' }],
  model: 'claude',
  params: { max_tokens: 500, stop_sequences: [], temperature: null },
  questions: {},
  state: '',
  summary: 'Saved from the workflow editor.',
  system: 'Be brief.',
  tools: [],
  variable_schema: { log: { required: true, type: 'any' } },
}

function draft(params: Record<string, unknown> = {}): WorkflowWrite {
  return {
    description: '',
    graph: {
      edges: [],
      nodes: [
        node({
          id: 'n1',
          key: 'summarize',
          params: { inputs: { log: '{{ fetch.result }}' }, ...params },
          title: 'Summarize',
          type: 'analysis',
        }),
      ],
    },
    name: 'Deploy guard',
    owner_team_slug: 'platform',
    settings: workflow().version.settings,
  }
}

const saved = workflow()
const calls: string[] = []

function savedParams() {
  const body = vi.mocked(endpoints.updateWorkflow).mock.calls[0][2]
  return body.graph.nodes[0].params
}

describe('saveWorkflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    calls.length = 0
    vi.mocked(endpoints.updateWorkflow).mockImplementation(async () => {
      calls.push('workflow')
      return saved
    })
  })

  it('creates a missing prompt, then saves the workflow with version 1', async () => {
    vi.mocked(endpoints.createPromptVersion).mockImplementation(async () => {
      calls.push('version')
      throw new ApiError(404, 'Not Found')
    })
    vi.mocked(endpoints.createPrompt).mockImplementation(async () => {
      calls.push('create')
      return { latest_version: 1 } as Prompt
    })

    const result = await saveWorkflow('acme', 'deploy-guard', draft(), {
      n1: PROMPT,
    })

    expect(calls).toEqual(['version', 'create', 'workflow'])
    expect(endpoints.createPrompt).toHaveBeenCalledWith({
      default_label: 'stable',
      kind: 'generative',
      name: 'Deploy guard / Summarize',
      namespace: 'workflows',
      slug: 'acme.deploy-guard.summarize',
      version: VERSION_BODY,
    })
    expect(savedParams()).toEqual({
      inputs: { log: '{{ fetch.result }}' },
      prompt_ref: 'workflows/acme.deploy-guard.summarize',
      prompt_version: 1,
    })
    expect(result.saved).toBe(saved)
  })

  it('adds a version to an existing prompt and pins its number', async () => {
    vi.mocked(endpoints.createPromptVersion).mockImplementation(async () => {
      calls.push('version')
      return { n: 3 } as PromptVersion
    })

    await saveWorkflow(
      'acme',
      'deploy-guard',
      draft({
        prompt_ref: 'workflows/acme.deploy-guard.summarize',
        prompt_version: 2,
      }),
      { n1: PROMPT },
    )

    expect(calls).toEqual(['version', 'workflow'])
    expect(endpoints.createPromptVersion).toHaveBeenCalledWith(
      'workflows',
      'acme.deploy-guard.summarize',
      VERSION_BODY,
    )
    expect(endpoints.createPrompt).not.toHaveBeenCalled()
    expect(savedParams().prompt_version).toBe(3)
  })

  it('writes nothing for an unchanged prompt that the node owns', async () => {
    const params = {
      prompt_ref: 'workflows/acme.deploy-guard.summarize',
      prompt_version: 2,
    }
    await saveWorkflow('acme', 'deploy-guard', draft(params), {})
    expect(endpoints.createPromptVersion).not.toHaveBeenCalled()
    expect(savedParams()).toMatchObject(params)
  })

  it('copies the pinned prompt to the slug of a renamed node key', async () => {
    vi.mocked(endpoints.resolvePrompt).mockResolvedValue({
      version: {
        messages: [{ content: 'Summarize {{ log }}', role: 'user' }],
        model: 'claude',
        params: { max_tokens: 500, stop_sequences: [] },
        system: 'Be brief.',
      },
    } as unknown as PromptResolution)
    vi.mocked(endpoints.createPromptVersion).mockRejectedValue(
      new ApiError(404, 'Not Found'),
    )
    vi.mocked(endpoints.createPrompt).mockResolvedValue({
      latest_version: 1,
    } as Prompt)

    await saveWorkflow(
      'acme',
      'deploy-guard',
      draft({
        prompt_ref: 'workflows/acme.deploy-guard.old_key',
        prompt_version: 4,
      }),
      {},
    )

    expect(endpoints.resolvePrompt).toHaveBeenCalledWith(
      'workflows/acme.deploy-guard.old_key@4',
    )
    expect(endpoints.createPrompt).toHaveBeenCalledWith(
      expect.objectContaining({
        slug: 'acme.deploy-guard.summarize',
        version: VERSION_BODY,
      }),
    )
    expect(savedParams()).toMatchObject({
      prompt_ref: 'workflows/acme.deploy-guard.summarize',
      prompt_version: 1,
    })
  })

  it('creates a new workflow first and uses the slug it gets', async () => {
    vi.mocked(endpoints.createWorkflow).mockImplementation(async () => {
      calls.push('create workflow')
      return { slug: 'deploy-guard-2' } as Workflow
    })
    vi.mocked(endpoints.createPromptVersion).mockImplementation(async () => {
      calls.push('version')
      return { n: 1 } as PromptVersion
    })
    const onCreated = vi.fn()

    await saveWorkflow(
      'acme',
      undefined,
      draft({
        prompt_ref: 'workflows/acme.other.summarize',
        prompt_version: 3,
      }),
      { n1: PROMPT },
      onCreated,
    )

    expect(calls).toEqual(['create workflow', 'version', 'workflow'])
    const created = vi.mocked(endpoints.createWorkflow).mock.calls[0][1]
    expect(created.graph.nodes[0].params).toEqual({
      inputs: { log: '{{ fetch.result }}' },
    })
    expect(onCreated).toHaveBeenCalledWith({ slug: 'deploy-guard-2' })
    expect(endpoints.createPromptVersion).toHaveBeenCalledWith(
      'workflows',
      'acme.deploy-guard-2.summarize',
      VERSION_BODY,
    )
    expect(vi.mocked(endpoints.updateWorkflow).mock.calls[0][1]).toBe(
      'deploy-guard-2',
    )
    expect(savedParams()).toMatchObject({
      prompt_ref: 'workflows/acme.deploy-guard-2.summarize',
      prompt_version: 1,
    })
  })

  it('refuses a prompt with no model', async () => {
    await expect(
      saveWorkflow('acme', 'deploy-guard', draft(), {
        n1: { ...PROMPT, model: null },
      }),
    ).rejects.toThrow("Step 'summarize': choose a model.")
    expect(endpoints.updateWorkflow).not.toHaveBeenCalled()
  })
})
