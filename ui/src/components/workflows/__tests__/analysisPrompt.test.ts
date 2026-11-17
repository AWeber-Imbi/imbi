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
  variable_schema: { log: { required: true, type: 'str' } },
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

  it('gives a new workflow the slug of its prompts', async () => {
    vi.mocked(endpoints.createPromptVersion).mockResolvedValue({
      n: 1,
    } as PromptVersion)
    vi.mocked(endpoints.createWorkflow).mockResolvedValue({} as Workflow)

    await saveWorkflow('acme', undefined, draft(), { n1: PROMPT })

    expect(endpoints.createPromptVersion).toHaveBeenCalledWith(
      'workflows',
      'acme.deploy-guard.summarize',
      VERSION_BODY,
    )
    expect(endpoints.createWorkflow).toHaveBeenCalledWith(
      'acme',
      expect.objectContaining({ slug: 'deploy-guard' }),
    )
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
