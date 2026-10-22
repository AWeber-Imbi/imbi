import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getPluginPackage,
  listIntegrations,
  listProjectIntegrations,
  replaceProjectIntegrations,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { ProjectIntegrationAssignment } from '@/types'

import { ProjectPluginsSection } from '../ProjectPluginsSection'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getPluginPackage: vi.fn(),
  listIntegrations: vi.fn(),
  listProjectIntegrations: vi.fn(),
  replaceProjectIntegrations: vi.fn(),
}))

const override: ProjectIntegrationAssignment = {
  capability: 'deployment',
  default: false,
  env_payloads: {},
  identity_integration_slug: null,
  integration_slug: 'github',
  options: {},
}

describe('ProjectPluginsSection environment payloads', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listProjectIntegrations).mockResolvedValue([override])
    vi.mocked(listIntegrations).mockResolvedValue([
      { capabilities: {}, name: 'GitHub', plugin: 'github', slug: 'github' },
    ] as never)
    vi.mocked(getPluginPackage).mockResolvedValue({
      capabilities: [{ kind: 'deployment', options: [] }],
    } as never)
    vi.mocked(replaceProjectIntegrations).mockResolvedValue([] as never)
  })

  it('saves edited payloads with the override', async () => {
    render(<ProjectPluginsSection orgSlug="acme" projectId="p-1" />)

    fireEvent.click(await screen.findByText('GitHub'))
    const editor = await screen.findByRole('textbox', {
      name: 'Environment payloads',
    })
    fireEvent.change(editor, {
      target: { value: '{"production": {"replicas": 3}}' },
    })
    fireEvent.blur(editor)
    fireEvent.click(await screen.findByRole('button', { name: 'Save Changes' }))

    await waitFor(() =>
      expect(replaceProjectIntegrations).toHaveBeenCalledWith('acme', 'p-1', {
        assignments: [
          { ...override, env_payloads: { production: { replicas: 3 } } },
        ],
      }),
    )
  })
})
