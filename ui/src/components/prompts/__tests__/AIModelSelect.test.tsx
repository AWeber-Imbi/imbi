import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { AIModel } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listAIModels: vi.fn(),
}))

const base: AIModel = {
  access_scope: 'organization',
  allowed_teams: [],
  context_window: null,
  default_temperature: null,
  default_top_p: null,
  enabled: true,
  id: 'model-1',
  input_cost_per_million: null,
  kind: 'chat',
  max_output_tokens: null,
  model_id: 'claude-fable-5-1',
  model_type: 'generative',
  monthly_spend_cap: null,
  name: 'Claude Fable 5.1',
  output_cost_per_million: null,
  provider_id: 'prov-1',
  provider_name: 'Anthropic',
  slug: 'default-chat',
}

describe('AIModelSelect', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([
      base,
      {
        ...base,
        id: 'model-2',
        model_id: 'jev-latest',
        model_type: 'decision',
        name: 'Jev',
        provider_id: 'prov-ts',
        provider_name: 'TypeSafe',
        slug: 'jev',
      },
    ])
  })

  it('lists generative models only', async () => {
    const endpoints = await import('@/api/endpoints')
    const { AIModelSelect } = await import('../AIModelSelect')
    render(<AIModelSelect onChange={vi.fn()} value={null} />)

    await waitFor(() => expect(endpoints.listAIModels).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('combobox', { name: 'Model' }))

    await waitFor(() =>
      expect(
        screen.getByRole('option', { name: /default-chat/ }),
      ).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('option', { name: /jev/ }),
    ).not.toBeInTheDocument()
  })
})
