import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { prompt, version } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPrompt: vi.fn(),
  createPromptVersion: vi.fn(),
  deletePrompt: vi.fn(),
  deletePromptLabel: vi.fn(),
  getPrompt: vi.fn(),
  listAIModels: vi.fn(),
  listPrompts: vi.fn(),
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

const assistant = prompt({
  id: 'prm-2',
  latest_version: 5,
  namespace: 'imbi-assistant',
  ref: 'imbi-assistant/system',
  slug: 'system',
})

async function renderLibrary(path = '/admin/prompts', namespace?: string) {
  window.history.pushState({}, '', path)
  const { PromptLibrary } = await import('../PromptLibrary')
  return render(<PromptLibrary namespace={namespace} />)
}

describe('PromptLibrary', () => {
  beforeEach(async () => {
    auth.user = { is_admin: true, permissions: [] }
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.listPrompts).mockResolvedValue([prompt(), assistant])
    vi.mocked(endpoints.getPrompt).mockResolvedValue(prompt())
    vi.mocked(endpoints.listPromptVersions).mockResolvedValue([
      version(2),
      version(1),
    ])
  })

  it('groups prompts by namespace in the tree', async () => {
    await renderLibrary()
    await waitFor(() =>
      expect(screen.getByText('imbi-assistant')).toBeInTheDocument(),
    )
    expect(screen.getByText('mender')).toBeInTheDocument()
    expect(screen.getByText('system')).toBeInTheDocument()
    expect(screen.getByText('v5')).toBeInTheDocument()
    expect(screen.getByText('Nothing selected')).toBeInTheDocument()
  })

  it('opens the selected prompt and keeps it in ?prompt=', async () => {
    await renderLibrary()
    await waitFor(() => expect(screen.getByText('core')).toBeInTheDocument())
    fireEvent.click(screen.getByText('core'))
    await waitFor(() =>
      expect(screen.getByText('mender/core@2')).toBeInTheDocument(),
    )
    expect(window.location.pathname).toBe('/admin/prompts')
    expect(new URLSearchParams(window.location.search).get('prompt')).toBe(
      'mender/core',
    )
  })

  it('restores the selection from ?prompt=', async () => {
    await renderLibrary('/admin/prompts?prompt=mender/core')
    await waitFor(() =>
      expect(screen.getByText('mender/core@2')).toBeInTheDocument(),
    )
  })

  it('limits the tree to one namespace', async () => {
    await renderLibrary('/admin/prompts', 'mender')
    await waitFor(() => expect(screen.getByText('core')).toBeInTheDocument())
    expect(screen.queryByText('imbi-assistant')).not.toBeInTheDocument()
  })

  it('hides New prompt without prompt:create', async () => {
    auth.user = { is_admin: false, permissions: ['prompt:read'] }
    await renderLibrary()
    await waitFor(() => expect(screen.getByText('mender')).toBeInTheDocument())
    expect(
      screen.queryByRole('button', { name: 'New prompt' }),
    ).not.toBeInTheDocument()
  })
})
