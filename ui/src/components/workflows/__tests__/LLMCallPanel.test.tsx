import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type {
  AIModel,
  Prompt,
  PromptResolution,
  PromptRunResponse,
} from '@/types'

import { LLMCallPanel } from '../LLMCallPanel'
import type { StepPrompt } from '../llmCallPrompt'
import type { WorkflowNode } from '../types'
import { node } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    selectedOrganization: { id: 'org-1', name: 'Acme', slug: 'acme' },
  }),
}))

vi.mock('@/api/endpoints', () => ({
  createPrompt: vi.fn(),
  listAIModels: vi.fn(),
  resolvePrompt: vi.fn(),
  runPrompt: vi.fn(),
}))

const MODEL = {
  enabled: true,
  id: 'm1',
  model_id: 'claude-x',
  model_type: 'generative',
  slug: 'claude',
  supports_forced_tool_choice: true,
  supports_structured_output: true,
} as AIModel

const PROMPT: StepPrompt = {
  max_tokens: null,
  model: 'claude',
  system: 'Be brief.',
  temperature: null,
  user: 'Summarize {{ log }}',
}

function renderPanel(
  params: Record<string, unknown>,
  prompt?: StepPrompt,
  workflowSlug: null | string = 'deploy-guard',
): WorkflowNode {
  const step = node({
    id: 'n1',
    key: 'summarize',
    params,
    title: 'Summarize',
    type: 'llm_call',
  })
  render(
    <LLMCallPanel
      node={step}
      onChange={vi.fn()}
      onPromptChange={vi.fn()}
      orgSlug="acme"
      prompt={prompt}
      references={[]}
      workflowName="Deploy guard"
      workflowSlug={workflowSlug ?? undefined}
    />,
  )
  return step
}

describe('LLMCallPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAIModels).mockResolvedValue([
      MODEL,
      { ...MODEL, id: 'm2', slug: 'plain', supports_structured_output: false },
    ])
  })

  it('loads the pinned prompt version of an existing node', async () => {
    vi.mocked(endpoints.resolvePrompt).mockResolvedValue({
      version: {
        messages: [{ content: 'Summarize {{ log }}', role: 'user' }],
        model: 'claude',
        params: { max_tokens: 800, stop_sequences: [] },
        system: 'Be brief.',
      },
    } as unknown as PromptResolution)
    renderPanel({
      prompt_ref: 'workflows/acme.deploy-guard.summarize',
      prompt_version: 2,
    })
    expect(await screen.findByLabelText('System prompt')).toHaveValue(
      'Be brief.',
    )
    expect(screen.getByLabelText('User message *')).toHaveValue(
      'Summarize {{ log }}',
    )
    expect(screen.getByLabelText('Max tokens')).toHaveValue(800)
    expect(endpoints.resolvePrompt).toHaveBeenCalledWith(
      'workflows/acme.deploy-guard.summarize@2',
      expect.anything(),
    )
  })

  it('blocks edits until the pinned prompt loads', async () => {
    vi.mocked(endpoints.resolvePrompt)
      .mockRejectedValueOnce(new ApiError(500, 'boom'))
      .mockResolvedValue({
        version: {
          messages: [{ content: 'Summarize {{ log }}', role: 'user' }],
          model: 'claude',
          params: { max_tokens: 800, stop_sequences: [] },
          system: 'Be brief.',
        },
      } as unknown as PromptResolution)
    renderPanel({
      prompt_ref: 'workflows/acme.deploy-guard.summarize',
      prompt_version: 2,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to load the prompt',
    )
    expect(screen.queryByLabelText('System prompt')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByLabelText('System prompt')).toHaveValue(
      'Be brief.',
    )
  })

  it('disables the output fields for a model with no structured output', async () => {
    renderPanel({}, { ...PROMPT, model: 'plain' })
    expect(
      await screen.findByText(/The model does not support structured output/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add field' })).toBeDisabled()
  })

  it('does not report missing structured output before the catalog loads', () => {
    vi.mocked(endpoints.listAIModels).mockReturnValue(new Promise(() => {}))
    renderPanel({ output_fields: [{ name: 'risk', type: 'string' }] }, PROMPT)
    expect(
      screen.queryByText(/does not support structured output/),
    ).not.toBeInTheDocument()
  })

  it('enables the output fields for a model with structured output', async () => {
    renderPanel({}, PROMPT)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Add field' })).toBeEnabled(),
    )
  })

  it('creates the prompt of a new node, then runs the draft', async () => {
    vi.mocked(endpoints.createPrompt).mockResolvedValue({} as Prompt)
    vi.mocked(endpoints.runPrompt).mockResolvedValue({
      cost_usd: 0.0012,
      model: 'claude',
      model_id: 'claude-x',
      text: 'All good.',
      usage: { input_tokens: 12, output_tokens: 3 },
    } as PromptRunResponse)
    renderPanel({ inputs: { log: '{{ fetch.result }}' } }, PROMPT)

    fireEvent.change(screen.getByLabelText('Sample inputs'), {
      target: { value: '{"log": "a line"}' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run prompt' }))

    expect(await screen.findByText('All good.')).toBeInTheDocument()
    expect(screen.getByText('$0.0012')).toBeInTheDocument()
    const version = {
      messages: [{ content: 'Summarize {{ log }}', role: 'user' }],
      model: 'claude',
      params: { max_tokens: null, stop_sequences: [], temperature: null },
      questions: {},
      state: '',
      system: 'Be brief.',
      tools: [],
      variable_schema: { log: { required: true, type: 'any' } },
    }
    expect(endpoints.createPrompt).toHaveBeenCalledWith(
      expect.objectContaining({
        namespace: 'workflows',
        slug: 'acme.deploy-guard.summarize',
        version,
      }),
    )
    expect(endpoints.runPrompt).toHaveBeenCalledWith('acme', {
      draft: {
        namespace: 'workflows',
        slug: 'acme.deploy-guard.summarize',
        version,
      },
      output_fields: [],
      variables: { log: 'a line' },
    })
  })

  it('runs the draft of a saved node without a new prompt', async () => {
    vi.mocked(endpoints.runPrompt).mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: { error: 'model_no_structured_output', retry: false },
      }),
    )
    renderPanel(
      {
        prompt_ref: 'workflows/acme.deploy-guard.summarize',
        prompt_version: 2,
      },
      PROMPT,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Run prompt' }))
    expect(
      await screen.findByText('Model no structured output'),
    ).toBeInTheDocument()
    expect(endpoints.createPrompt).not.toHaveBeenCalled()
  })

  it('does not run the prompt of a workflow that is not saved', () => {
    renderPanel({}, PROMPT, null)
    expect(screen.getByRole('button', { name: 'Run prompt' })).toBeDisabled()
    expect(screen.getByText('Save the workflow first.')).toBeInTheDocument()
  })
})
