import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'
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
  capabilities: [],
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
})
