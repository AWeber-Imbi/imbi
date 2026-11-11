import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'
import type { AIModel } from '@/types'

import { type PromptDraft, promptDraftFromVersion } from '../agentDraft'
import { ModelTab } from '../ModelTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listAIModels: vi.fn(),
}))

const opus: AIModel = {
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
  model_id: 'claude-opus-5-5',
  model_type: 'generative',
  monthly_spend_cap: null,
  name: 'Claude Opus 5.5',
  output_cost_per_million: null,
  provider_id: 'prov-1',
  provider_name: 'Anthropic',
  slug: 'claude-opus-5-5',
}

const gpt: AIModel = {
  ...opus,
  id: 'model-2',
  model_id: 'gpt-5',
  name: 'GPT-5',
  provider_id: 'prov-2',
  provider_name: 'OpenAI',
  slug: 'gpt-5',
}

const changes: PromptDraft[] = []

function Harness({ initial }: { initial: PromptDraft }) {
  const [value, setValue] = useState(initial)
  return (
    <ModelTab
      errors={{}}
      onChange={(next) => {
        changes.push(next)
        setValue(next)
      }}
      value={value}
    />
  )
}

function last(): PromptDraft {
  return changes[changes.length - 1]
}

async function pickModel(slug: string) {
  fireEvent.click(screen.getByRole('button', { name: 'Model' }))
  fireEvent.click(await screen.findByRole('option', { name: slug }))
}

describe('ModelTab', () => {
  beforeEach(() => {
    changes.length = 0
    vi.mocked(endpoints.listAIModels).mockResolvedValue([opus, gpt])
  })

  it('sets medium effort when a Claude model is picked', async () => {
    render(<Harness initial={promptDraftFromVersion(null)} />)
    expect(screen.queryByRole('combobox', { name: 'Effort' })).toBeNull()

    await pickModel('claude-opus-5-5')

    expect(last()).toMatchObject({
      effort: 'medium',
      model: 'claude-opus-5-5',
    })
    expect(screen.getByRole('combobox', { name: 'Effort' })).toHaveTextContent(
      'Medium',
    )
  })

  it('offers only the controls the agent runtime applies', () => {
    render(<Harness initial={promptDraftFromVersion(null)} />)
    fireEvent.click(
      screen.getByRole('button', { name: /Show advanced controls/ }),
    )
    expect(screen.getByText('Max tokens')).toBeInTheDocument()
    expect(screen.getByText('Prompt caching')).toBeInTheDocument()
    for (const removed of [
      'Extended thinking',
      'Temperature',
      'Top K',
      'Top P',
    ])
      expect(screen.queryByText(removed)).toBeNull()
  })
})
