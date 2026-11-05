import { fireEvent, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type {
  SecretBinding,
  SecretGrant,
} from '@/components/admin/secrets/types'
import { render, screen } from '@/test/utils'

import { AccessTab } from '../AccessTab'
import { emptyDraft } from '../agentDraft'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createSecretGrant: vi.fn(),
  listSecretBindings: vi.fn(),
  listSecretGrants: vi.fn(),
  listSecretProviders: vi.fn(),
}))

const auth = vi.hoisted(() => ({
  user: {
    is_admin: true,
    organizations: [{ organization_slug: 'acme', permissions: [] }],
    permissions: [] as string[],
  },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const AGENT = { id: 'agt-1', name: 'Mender' }

function binding(
  id: string,
  reference: string,
  allowed_fields: string[] = [],
  changes: Partial<SecretBinding> = {},
): SecretBinding {
  return {
    allowed_delivery_modes: ['file_descriptor', 'environment'],
    allowed_fields,
    enabled: true,
    id,
    max_ttl_seconds: 3600,
    provider_id: 'p-1',
    reference,
    ...changes,
  } as SecretBinding
}

function grant(changes: Partial<SecretGrant>): SecretGrant {
  return {
    agent_ids: [AGENT.id],
    binding_ids: [],
    delivery_modes: ['environment'],
    enabled: true,
    id: crypto.randomUUID(),
    max_ttl_seconds: 900,
    project_ids: [],
    purposes: [],
    ...changes,
  } as SecretGrant
}

describe('AccessTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listSecretProviders).mockResolvedValue([])
    vi.mocked(endpoints.listSecretBindings).mockResolvedValue([
      binding('b-gh', 'secret://dev/github_app'),
      binding('b-npm', 'secret://ci/npm_token'),
      binding('b-key', 'secret://anthropic/triage', ['api-key']),
      binding('b-env', 'secret://anthropic/env_only', [], {
        allowed_delivery_modes: ['environment'],
      }),
    ])
    vi.mocked(endpoints.listSecretGrants).mockResolvedValue([
      grant({
        binding_ids: ['b-gh'],
        delivery_modes: ['file_descriptor'],
        purposes: ['workspace_checkout'],
      }),
      grant({
        agent_ids: [AGENT.id, 'agt-2'],
        binding_ids: ['b-npm'],
        purposes: ['npm'],
      }),
      // Another agent's grant and a disabled grant do not count.
      grant({ agent_ids: ['agt-2'], binding_ids: ['b-gh'] }),
      grant({
        binding_ids: ['b-gh'],
        enabled: false,
        purposes: ['github_write'],
      }),
    ])
    vi.mocked(endpoints.createSecretGrant).mockResolvedValue(grant({}) as never)
  })

  function renderTab(modelKeyRef = '') {
    render(
      <AccessTab
        agent={AGENT}
        errors={{}}
        onChange={vi.fn()}
        orgSlug="acme"
        value={{
          ...emptyDraft().settings,
          githubAppBinding: 'secret://dev/github_app',
          modelKeyRef,
        }}
      />,
    )
  }

  it('shows each GitHub App purpose and grants a missing one', async () => {
    renderTab()
    const write = (
      await screen.findByText('Push, and open pull requests and issues')
    ).closest('li')!
    const checkout = screen
      .getByText('Clone the project repositories')
      .closest('li')!
    expect(within(checkout).queryByRole('button')).not.toBeInTheDocument()
    fireEvent.click(within(write).getByRole('button', { name: 'Grant' }))
    await waitFor(() =>
      expect(endpoints.createSecretGrant).toHaveBeenCalledWith('acme', {
        agent_ids: [AGENT.id],
        binding_ids: ['b-gh'],
        delivery_modes: ['environment'],
        description: 'Mender: github_write with secret://dev/github_app',
        enabled: true,
        max_ttl_seconds: 900,
        project_ids: [],
        purposes: ['github_write'],
      }),
    )
  })

  it('grants the model key that the agent uses', async () => {
    renderTab('secret://anthropic/triage#api-key')
    const row = (await screen.findByText('Call the model')).closest('div')!
    fireEvent.click(within(row).getByRole('button', { name: 'Grant' }))
    await waitFor(() =>
      expect(endpoints.createSecretGrant).toHaveBeenCalledWith('acme', {
        agent_ids: [AGENT.id],
        binding_ids: ['b-key'],
        delivery_modes: ['file_descriptor'],
        description: 'Mender: model_inference with secret://anthropic/triage',
        enabled: true,
        max_ttl_seconds: 900,
        project_ids: [],
        purposes: ['model_inference'],
      }),
    )
  })

  it('marks a saved model key that cannot supply a key', async () => {
    renderTab('secret://anthropic/env_only')
    expect(
      await screen.findByText(/This binding cannot supply a model key/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Call the model')).not.toBeInTheDocument()
  })

  it('uses the organization key when the agent has none', () => {
    renderTab()
    expect(screen.queryByText('Call the model')).not.toBeInTheDocument()
  })

  it('lists the secrets that the agent has grants for', async () => {
    renderTab()
    expect(await screen.findByText('secret://ci/npm_token')).toBeInTheDocument()
    expect(screen.getByText(/shared with 1 other agent/)).toBeInTheDocument()
    expect(screen.getByText('npm')).toBeInTheDocument()
  })

  it('asks for a save before a new agent gets access', () => {
    render(
      <AccessTab
        agent={null}
        errors={{}}
        onChange={vi.fn()}
        orgSlug="acme"
        value={emptyDraft().settings}
      />,
    )
    expect(
      screen.getByText(/Save the agent first to give it access/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Add access/ }),
    ).not.toBeInTheDocument()
  })
})
