import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { Prompt, PromptVersion } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  deletePrompt: vi.fn(),
  deletePromptLabel: vi.fn(),
  listAIModels: vi.fn(),
  listPrompts: vi.fn(),
  listPromptVersions: vi.fn(),
  setPromptDefaultLabel: vi.fn(),
  setPromptLabel: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

const auth = vi.hoisted(() => ({
  user: { is_admin: true, permissions: [] as string[] },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const prompt = (overrides: Partial<Prompt> = {}): Prompt => ({
  created_at: '2026-10-01T12:00:00Z',
  default_label: 'stable',
  id: 'prm-1',
  labels: [
    {
      name: 'stable',
      updated_at: '2026-10-01T12:00:00Z',
      updated_by: 'grantr@example.com',
      version: 2,
    },
  ],
  latest_version: 2,
  name: 'Mender core',
  namespace: 'mender',
  ref: 'mender/core',
  slug: 'core',
  type: 'core_system',
  updated_at: '2026-10-01T12:00:00Z',
  ...overrides,
})

const version = (n: number): PromptVersion => ({
  content_sha256: `${n}`.repeat(64),
  created_at: '2026-10-01T12:00:00Z',
  created_by: 'grantr@example.com',
  eval_summary: null,
  id: `ver-${n}`,
  labels: n === 2 ? ['stable'] : [],
  messages: [],
  model: null,
  model_id: null,
  n,
  params: { max_tokens: 4096, stop_sequences: [], temperature: 1 },
  ref: `mender/core@${n}`,
  summary: `Change ${n}`,
  system: `You triage v${n}.`,
  tools: [],
  variable_schema: {},
})

async function renderAt(path: string) {
  window.history.pushState({}, '', path)
  const { PromptCMS } = await import('../PromptCMS')
  return render(
    <Routes>
      <Route element={<PromptCMS />} path="/prompts/:namespace?/:slug?" />
    </Routes>,
  )
}

describe('PromptCMS', () => {
  beforeEach(async () => {
    auth.user = { is_admin: true, permissions: [] }
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.listPrompts).mockResolvedValue([
      prompt(),
      prompt({
        id: 'prm-2',
        latest_version: 5,
        namespace: 'imbi-assistant',
        ref: 'imbi-assistant/system',
        slug: 'system',
      }),
    ])
    vi.mocked(endpoints.listPromptVersions).mockResolvedValue([
      version(2),
      version(1),
    ])
  })

  it('groups prompts by namespace in the tree', async () => {
    await renderAt('/prompts')
    await waitFor(() =>
      expect(screen.getByText('imbi-assistant')).toBeInTheDocument(),
    )
    expect(screen.getByText('mender')).toBeInTheDocument()
    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('v5')).toBeInTheDocument()
    expect(screen.getByText('Nothing selected')).toBeInTheDocument()
  })

  it('saves a new version with the change summary', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.createPromptVersion).mockResolvedValue(version(3))
    await renderAt('/prompts/mender/core')

    await waitFor(() =>
      expect(screen.getByText('mender/core@2')).toBeInTheDocument(),
    )
    const save = screen.getByRole('button', { name: 'Save version' })
    expect(save).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Temperature'), {
      target: { value: '0.5' },
    })
    fireEvent.change(screen.getByLabelText('Change summary'), {
      target: { value: 'Cooler' },
    })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() =>
      expect(endpoints.createPromptVersion).toHaveBeenCalledWith(
        'acme',
        'mender',
        'core',
        expect.objectContaining({
          params: expect.objectContaining({ temperature: 0.5 }),
          summary: 'Cooler',
          system: 'You triage v2.',
        }),
      ),
    )
  })

  it('hides promote and editing without the permissions', async () => {
    auth.user = { is_admin: false, permissions: ['prompt:read'] }
    await renderAt('/prompts/mender/core')

    await waitFor(() =>
      expect(screen.getByText('mender/core@2')).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('button', { name: /promote/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Save version' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'New prompt' }),
    ).not.toBeInTheDocument()
  })
})
