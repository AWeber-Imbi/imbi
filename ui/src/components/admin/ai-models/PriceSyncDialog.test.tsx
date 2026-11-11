import { describe, expect, it, vi } from 'vitest'

import { applyAIModelPrices } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { AIPriceSyncPreview } from '@/types'

import { PriceSyncDialog } from './PriceSyncDialog'

const preview: AIPriceSyncPreview = {
  models: [
    {
      fields: [
        {
          current: '3',
          field: 'input_cost_per_million',
          litellm: '5',
        },
        {
          current: null,
          field: 'cache_read_cost_per_million',
          litellm: '0.5',
        },
      ],
      id: 'mdl-1',
      litellm_key: 'claude-opus-5',
      name: 'Opus',
      provider_name: 'Anthropic',
    },
    {
      fields: [
        {
          current: '2',
          field: 'input_cost_per_million',
          litellm: '2.5',
        },
      ],
      id: 'mdl-2',
      litellm_key: 'gpt-5',
      name: 'GPT',
      provider_name: 'OpenAI',
    },
  ],
  unmatched: ['Llama'],
  up_to_date: 3,
}

vi.mock('@/api/endpoints', () => ({
  applyAIModelPrices: vi.fn().mockResolvedValue({ skipped: [], updated: [] }),
  previewAIModelPrices: vi.fn(() => Promise.resolve(preview)),
}))

describe('PriceSyncDialog', () => {
  it('fills missing prices and overwrites only opted-in models', async () => {
    const onApplied = vi.fn()
    render(<PriceSyncDialog onApplied={onApplied} onClose={vi.fn()} />)

    expect(
      await screen.findByText(/2 to update, 3 up to date, 1 not in LiteLLM/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Llama/)).toBeInTheDocument()

    // GPT only has a set price, so it applies only with overwrite.
    const apply = screen.getByRole('button', { name: /Apply to 1 model$/ })
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Overwrite set prices for GPT' }),
    )
    expect(
      screen.getByRole('button', { name: /Apply to 2 models/ }),
    ).toBeInTheDocument()

    fireEvent.click(apply)
    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    expect(vi.mocked(applyAIModelPrices).mock.calls[0][0]).toEqual({
      models: [
        { id: 'mdl-1', overwrite: false },
        { id: 'mdl-2', overwrite: true },
      ],
    })
  })
})
