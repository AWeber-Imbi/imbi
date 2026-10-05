import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { prompt, version } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPromptVersion: vi.fn(),
  deletePrompt: vi.fn(),
  deletePromptLabel: vi.fn(),
  getPrompt: vi.fn(),
  listAIModels: vi.fn(),
  listPromptVersions: vi.fn(),
  setPromptDefaultLabel: vi.fn(),
  setPromptLabel: vi.fn(),
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

async function renderEditor(emptyState?: React.ReactNode) {
  const { PromptEditor } = await import('../PromptEditor')
  return render(
    <PromptEditor emptyState={emptyState} namespace="mender" slug="core" />,
  )
}

describe('PromptEditor', () => {
  // Load the component once, outside the 5 s test timeout. On CI the
  // cold import of the CodeMirror prompt editor takes longer than that.
  beforeAll(async () => {
    await import('../PromptEditor')
  }, 60_000)

  beforeEach(async () => {
    auth.user = { is_admin: true, permissions: [] }
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.getPrompt).mockResolvedValue(prompt())
    vi.mocked(endpoints.listPromptVersions).mockResolvedValue([
      version(2),
      version(1),
    ])
  })

  it('renders one prompt without a router param or tree', async () => {
    const endpoints = await import('@/api/endpoints')
    await renderEditor()
    await waitFor(() =>
      expect(screen.getByText('mender/core@2')).toBeInTheDocument(),
    )
    expect(endpoints.getPrompt).toHaveBeenCalledWith(
      'mender',
      'core',
      expect.anything(),
    )
    expect(screen.getByText('mender/core')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /promote/i })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('renders a prompt that has no labels yet', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getPrompt).mockResolvedValue(prompt({ labels: [] }))
    await renderEditor()
    await waitFor(() =>
      expect(screen.getByText(/No labels yet/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/does not resolve/)).toBeInTheDocument()
    expect(screen.queryByText(/changes what every consumer/)).toBeNull()
    expect(screen.getByRole('button', { name: /promote/i })).toBeInTheDocument()
  })

  it('renders the empty state when the prompt does not exist', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.getPrompt).mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: 'Prompt not found' }),
    )
    await renderEditor(<p>Nothing here</p>)
    await waitFor(() =>
      expect(screen.getByText('Nothing here')).toBeInTheDocument(),
    )
  })

  it('saves a new version with the change summary', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.createPromptVersion).mockResolvedValue(version(3))
    await renderEditor()
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
    await renderEditor()
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
      screen.queryByRole('button', { name: 'Delete prompt' }),
    ).not.toBeInTheDocument()
  })
})
