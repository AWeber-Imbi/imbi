import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { PromptVersion } from '@/types'

import { prompt, version } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPromptVersion: vi.fn(),
  deletePrompt: vi.fn(),
  deletePromptLabel: vi.fn(),
  getPrompt: vi.fn(),
  listAIModels: vi.fn(),
  listPromptVersions: vi.fn(),
  runPrompt: vi.fn(),
  setPromptDefaultLabel: vi.fn(),
  setPromptLabel: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

const decisionVersion = (n: number): PromptVersion => ({
  ...version(n),
  model: 'jev',
  params: { stop_sequences: [] },
  questions: {
    urgent: {
      criteria: { false: 'Up', true: 'Down' },
      instructions: 'Is {{ service }} down?',
      type: 'noul',
    },
  },
  ref: `mender/triage@${n}`,
  state: '{"service": {{ service | tojson }}}',
  system: '',
  variable_schema: { service: { required: true, type: 'str' } },
})

async function renderEditor() {
  const { PromptEditor } = await import('../PromptEditor')
  return render(<PromptEditor namespace="mender" slug="triage" />)
}

describe('Decision prompts', () => {
  beforeAll(async () => {
    await import('../PromptEditor')
  }, 60_000)

  beforeEach(async () => {
    vi.clearAllMocks()
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.getPrompt).mockResolvedValue(
      prompt({ kind: 'decision', ref: 'mender/triage', slug: 'triage' }),
    )
    vi.mocked(endpoints.listPromptVersions).mockResolvedValue([
      decisionVersion(2),
      decisionVersion(1),
    ])
  })

  it('edits a state and questions instead of a body', async () => {
    await renderEditor()
    await waitFor(() =>
      expect(screen.getByLabelText('Question 1 id')).toHaveValue('urgent'),
    )
    expect(screen.getByText('State')).toBeInTheDocument()
    expect(screen.getByText('Questions')).toBeInTheDocument()
    expect(screen.queryByText('Messages')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Temperature')).not.toBeInTheDocument()
    expect(screen.getByText('decision')).toBeInTheDocument()
  })

  it('saves questions with no generative fields', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.createPromptVersion).mockResolvedValue(
      decisionVersion(3),
    )
    await renderEditor()
    await waitFor(() =>
      expect(screen.getByLabelText('Question 1 id')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /add question/i }))
    fireEvent.change(screen.getByLabelText('Question 2 instructions'), {
      target: { value: 'Is it new?' },
    })
    fireEvent.change(screen.getByLabelText('Change summary'), {
      target: { value: 'Ask about novelty' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save version/i }))
    await waitFor(() =>
      expect(endpoints.createPromptVersion).toHaveBeenCalled(),
    )
    const body = vi.mocked(endpoints.createPromptVersion).mock.calls[0][2]
    expect(body.system).toBe('')
    expect(body.messages).toEqual([])
    expect(body.questions?.q2).toEqual({
      criteria: null,
      instructions: 'Is it new?',
      type: 'noul',
    })
    expect(body.state).toBe('{"service": {{ service | tojson }}}')
  })

  it('runs the draft and shows typed answers', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.runPrompt).mockResolvedValue({
      answers: {
        team: {
          choice: 'payments',
          confidence: 0.7,
          probabilities: { other: 0.2, payments: 0.8 },
          type: 'choice',
        },
        urgent: { noul: 0.91, type: 'noul' },
      },
      model: 'jev',
      model_id: 'jev-latest',
      n: null,
      ref: 'mender/triage (draft)',
      request: { questions: {}, state: { service: 'billing' } },
      usage: { input_tokens: 20, output_tokens: 2 },
    })
    await renderEditor()
    await waitFor(() =>
      expect(screen.getByLabelText('Run variable service')).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('Run variable service'), {
      target: { value: 'billing' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^run$/i }))
    await waitFor(() =>
      expect(screen.getByTestId('run-result')).toBeInTheDocument(),
    )
    const [org, request] = vi.mocked(endpoints.runPrompt).mock.calls[0]
    expect(org).toBe('acme')
    expect(request.variables).toEqual({ service: 'billing' })
    expect(request.draft?.slug).toBe('triage')
    expect(screen.getByText('91%')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
    expect(screen.getByText(/20 in/)).toBeInTheDocument()
  })
})

describe('Question helpers', () => {
  it('round-trips and validates questions', async () => {
    const { questionErrors, questionRowsFrom, questionsFrom } =
      await import('../DecisionEditor')
    const questions = {
      impact: {
        criteria: ['None', 'All'],
        instructions: 'How bad?',
        type: 'score' as const,
      },
      team: {
        criteria: { other: null, payments: 'Billing' },
        instructions: 'Which team?',
        type: 'choice' as const,
      },
    }
    const rows = questionRowsFrom(questions)
    expect(questionsFrom(rows)).toEqual(questions)
    expect(questionErrors(rows)).toEqual([])
    expect(questionErrors([{ ...rows[0], levels: ['only one'] }])).toContain(
      'Question impact: 2 to 10 levels',
    )
    expect(questionErrors([{ ...rows[0], id: 'bad id' }])).toContain(
      'Question ids must be identifiers',
    )
  })
})
