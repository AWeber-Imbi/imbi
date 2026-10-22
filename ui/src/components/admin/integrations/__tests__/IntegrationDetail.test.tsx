import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getIntegration,
  listCapabilityAssignments,
  listPluginPackages,
  listProjectTypes,
  replaceCapabilityAssignments,
  updateIntegration,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { CapabilityAssignment, Integration, PluginPackage } from '@/types'

import { IntegrationDetail } from '../IntegrationDetail'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteIntegration: vi.fn(),
  getIntegration: vi.fn(),
  listCapabilityAssignments: vi.fn(),
  listPluginPackages: vi.fn(),
  listProjectTypes: vi.fn(),
  listWebhooks: vi.fn().mockResolvedValue([]),
  replaceCapabilityAssignments: vi.fn(),
  updateIntegration: vi.fn(),
  updateIntegrationCredentials: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const integrationWithStatus = (status: string) =>
  ({
    capabilities: {},
    credential_fields: [],
    id: 'i-1',
    name: 'GitHub',
    options: {},
    plugin: 'github',
    slug: 'github',
    status,
  }) as unknown as Integration

const renderDetail = (status: string) => {
  vi.mocked(getIntegration).mockResolvedValue(integrationWithStatus(status))
  return render(
    <IntegrationDetail
      onBack={vi.fn()}
      seed={integrationWithStatus(status)}
      slug="github"
    />,
  )
}

describe('IntegrationDetail danger zone', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listPluginPackages).mockResolvedValue([])
    vi.mocked(listProjectTypes).mockResolvedValue([])
    vi.mocked(updateIntegration).mockResolvedValue({} as never)
  })

  it('disables an active integration', async () => {
    renderDetail('active')
    fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))
    await waitFor(() =>
      expect(updateIntegration).toHaveBeenCalledWith('acme', 'github', {
        status: 'inactive',
      }),
    )
  })

  it('enables an inactive integration', async () => {
    renderDetail('inactive')
    expect(await screen.findByText('Enable integration')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }))
    await waitFor(() =>
      expect(updateIntegration).toHaveBeenCalledWith('acme', 'github', {
        status: 'active',
      }),
    )
  })
})

const integration = {
  capabilities: { deployment: { enabled: true, options: {} } },
  credential_fields: [],
  name: 'GitHub',
  options: {},
  plugin: 'github',
  slug: 'github',
  status: 'active',
} as unknown as Integration

const plugin = {
  capabilities: [
    {
      description: null,
      kind: 'deployment',
      label: 'Deployment',
      options: [],
      project_scoped: true,
    },
  ],
  credentials: [],
  enabled: true,
  options: [],
  slug: 'github',
} as unknown as PluginPackage

const existing: CapabilityAssignment = {
  default: true,
  env_payloads: { production: { region: 'us-east-1' } },
  identity_integration_slug: 'github-identity',
  options: { workflow: 'deploy.yml' },
  project_type_slug: 'api',
}

describe('IntegrationDetail assignments', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getIntegration).mockResolvedValue(integration)
    vi.mocked(listPluginPackages).mockResolvedValue([plugin])
    vi.mocked(listProjectTypes).mockResolvedValue([
      { name: 'API', slug: 'api' },
      { name: 'Consumer', slug: 'consumer' },
    ] as never)
    vi.mocked(listCapabilityAssignments).mockResolvedValue([existing])
    vi.mocked(replaceCapabilityAssignments).mockResolvedValue([])
  })

  it('keeps existing assignment values when a project type is added', async () => {
    render(
      <IntegrationDetail onBack={vi.fn()} seed={integration} slug="github" />,
    )

    // The assigned type renders once the current assignments are loaded.
    await screen.findAllByText('API')
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Consumer' }))

    await waitFor(() =>
      expect(replaceCapabilityAssignments).toHaveBeenCalledWith(
        'acme',
        'github',
        'deployment',
        {
          assignments: [
            existing,
            {
              default: false,
              env_payloads: {},
              identity_integration_slug: null,
              options: {},
              project_type_slug: 'consumer',
            },
          ],
        },
      ),
    )
  })

  it('saves edited environment payloads for one project type', async () => {
    render(
      <IntegrationDetail onBack={vi.fn()} seed={integration} slug="github" />,
    )

    const editor = await screen.findByRole('textbox', {
      name: 'API environment payloads',
    })
    expect(editor).toHaveValue(JSON.stringify(existing.env_payloads, null, 2))
    fireEvent.change(editor, {
      target: { value: '{"staging": {"region": "us-west-2"}}' },
    })
    fireEvent.blur(editor)

    await waitFor(() =>
      expect(replaceCapabilityAssignments).toHaveBeenCalledWith(
        'acme',
        'github',
        'deployment',
        {
          assignments: [
            {
              ...existing,
              env_payloads: { staging: { region: 'us-west-2' } },
            },
          ],
        },
      ),
    )
  })

  it('does not save invalid environment payloads', async () => {
    render(
      <IntegrationDetail onBack={vi.fn()} seed={integration} slug="github" />,
    )

    const editor = await screen.findByRole('textbox', {
      name: 'API environment payloads',
    })
    fireEvent.change(editor, { target: { value: '{"staging": 1}' } })
    fireEvent.blur(editor)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The payload for "staging" must be a JSON object.',
    )
    expect(editor).toHaveAccessibleDescription(
      'The payload for "staging" must be a JSON object.',
    )
    expect(replaceCapabilityAssignments).not.toHaveBeenCalled()
  })
})
