import { describe, expect, it, vi } from 'vitest'

import { createIntegration } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { PluginPackage } from '@/types'

import { IntegrationWizard } from '../IntegrationWizard'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createIntegration: vi.fn(),
  listProjectTypes: vi.fn().mockResolvedValue([]),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const sole = {
  capabilities: [
    {
      default_enabled: true,
      description: 'Tools',
      kind: 'tools',
      label: 'Tools',
      options: [
        { default: 'm1', label: 'Model', name: 'model', type: 'string' },
      ],
      project_scoped: false,
    },
  ],
  credentials: [],
  enabled: true,
  name: 'Sole',
  options: [
    {
      default: 'https://example.com',
      label: 'Base URL',
      name: 'base_url',
      required: true,
      type: 'string',
    },
  ],
  slug: 'sole',
} as unknown as PluginPackage

describe('IntegrationWizard', () => {
  it('initializes a sole plugin that loads after mount', () => {
    const props = { onCancel: vi.fn(), onCreated: vi.fn() }
    const { rerender } = render(<IntegrationWizard {...props} plugins={[]} />)
    rerender(<IntegrationWizard {...props} plugins={[sole]} />)
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(screen.getByDisplayValue('https://example.com')).toBeInTheDocument()
  })

  it('submits the initialized capabilities of a sole plugin', async () => {
    vi.mocked(createIntegration).mockResolvedValue({
      slug: 'sole',
    } as Awaited<ReturnType<typeof createIntegration>>)
    const props = { onCancel: vi.fn(), onCreated: vi.fn() }
    render(<IntegrationWizard {...props} plugins={[sole]} />)
    const next = () =>
      fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    next()
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Sole' },
    })
    next()
    next()
    fireEvent.click(screen.getByRole('button', { name: /create integration/i }))
    await waitFor(() =>
      expect(createIntegration).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({
          capabilities: { tools: { enabled: true, options: { model: 'm1' } } },
        }),
      ),
    )
  })
})
