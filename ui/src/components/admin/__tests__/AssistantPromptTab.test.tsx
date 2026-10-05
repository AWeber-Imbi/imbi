import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createPrompt: vi.fn(),
  getPrompt: vi.fn(),
  listAIModels: vi.fn(),
  listPromptVersions: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

describe('AssistantPromptTab', () => {
  beforeEach(async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIModels).mockResolvedValue([])
    vi.mocked(endpoints.getPrompt).mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: 'Prompt not found' }),
    )
  })

  it('offers to create the assistant prompt when it is missing', async () => {
    const endpoints = await import('@/api/endpoints')
    const { AssistantPromptTab } = await import('../AssistantPromptTab')
    render(<AssistantPromptTab />)

    await waitFor(() =>
      expect(
        screen.getByText('The assistant prompt is not in the CMS yet'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByText(/reads this prompt after the CMS adoption change ships/),
    ).toBeInTheDocument()
    expect(endpoints.getPrompt).toHaveBeenCalledWith(
      'acme',
      'imbi-assistant',
      'system',
      expect.anything(),
    )
  })

  it('creates the prompt with locked, prefilled fields', async () => {
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.createPrompt).mockResolvedValue(
      {} as Awaited<ReturnType<typeof endpoints.createPrompt>>,
    )
    const { AssistantPromptTab } = await import('../AssistantPromptTab')
    render(<AssistantPromptTab />)

    fireEvent.click(
      await screen.findByRole('button', { name: 'Create assistant prompt' }),
    )
    const namespace = screen.getByLabelText(/namespace/i)
    expect(namespace).toHaveValue('imbi-assistant')
    expect(namespace).toBeDisabled()
    expect(screen.getByLabelText(/^slug/i)).toHaveValue('system')
    expect(screen.getByLabelText(/^slug/i)).toBeDisabled()
    expect(screen.getByLabelText(/^name(?!space)/i)).toHaveValue(
      'Assistant system prompt',
    )
    expect(screen.getByLabelText(/^type/i)).toHaveValue('core_system')

    fireEvent.click(screen.getByRole('button', { name: 'Create prompt' }))
    await waitFor(() =>
      expect(endpoints.createPrompt).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({
          name: 'Assistant system prompt',
          namespace: 'imbi-assistant',
          slug: 'system',
          type: 'core_system',
        }),
      ),
    )
  })
})
