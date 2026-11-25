import { fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
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
  removeSecretGrantAgent: vi.fn(),
  updateSecretGrant: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}))

const ADMIN = {
  is_admin: true,
  organizations: [{ organization_slug: 'acme', permissions: [] as string[] }],
  permissions: [] as string[],
  teams: [] as { organization_slug: string; team_slug: string }[],
}
const auth = vi.hoisted(() => ({ user: {} as typeof ADMIN }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const AGENT = { id: 'agt-1', name: 'Mender', team: 'ops' }

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

/** A developer: grant access, no binding write. */
function developer(teams: string[]) {
  auth.user = {
    is_admin: false,
    organizations: [
      {
        organization_slug: 'acme',
        permissions: [
          'secret_binding:read',
          'secret_grant:read',
          'secret_grant:write',
        ],
      },
    ],
    permissions: [],
    teams: teams.map((t) => ({ organization_slug: 'acme', team_slug: t })),
  }
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
    auth.user = ADMIN
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
    vi.mocked(endpoints.updateSecretGrant).mockResolvedValue(grant({}) as never)
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
    expect(
      within(checkout).queryByRole('button', { name: 'Grant' }),
    ).not.toBeInTheDocument()
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

  it('adds a purpose to the agent grant of the same secret', async () => {
    renderTab()
    const fetch = (
      await screen.findByText('Fetch plugins from private marketplaces')
    ).closest('li')!
    fireEvent.click(within(fetch).getByRole('button', { name: 'Grant' }))
    // The agent's own file_descriptor grant of the GitHub App binding
    // gets the purpose; no second grant for the same secret.
    await waitFor(() =>
      expect(endpoints.updateSecretGrant).toHaveBeenCalledWith(
        'acme',
        expect.any(String),
        { purposes: ['workspace_checkout', 'marketplace_fetch'] },
      ),
    )
    expect(endpoints.createSecretGrant).not.toHaveBeenCalled()
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

  it('marks a saved model key field that the binding no longer allows', async () => {
    renderTab('secret://anthropic/triage#old-key')
    expect(
      await screen.findByText(/This binding cannot supply a model key/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Call the model')).not.toBeInTheDocument()
  })

  it('marks a saved model key field when the binding allows no fields', async () => {
    renderTab('secret://ci/npm_token#api-key')
    expect(
      await screen.findByText(/This binding cannot supply a model key/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Call the model')).not.toBeInTheDocument()
  })

  it('marks a saved model key whose binding is gone', async () => {
    renderTab('secret://anthropic/deleted#api-key')
    expect(
      await screen.findByText(/This binding does not exist/),
    ).toBeInTheDocument()
  })

  it('does not mark a missing binding before the bindings load', () => {
    vi.mocked(endpoints.listSecretBindings).mockReturnValue(
      new Promise(() => {}),
    )
    renderTab('secret://anthropic/deleted#api-key')
    expect(
      screen.queryByText(/This binding does not exist/),
    ).not.toBeInTheDocument()
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

  it('removes the agent from a grant', async () => {
    vi.mocked(endpoints.removeSecretGrantAgent).mockResolvedValue(undefined)
    renderTab()
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Remove secret://ci/npm_token',
      }),
    )
    const shared = (await endpoints.listSecretGrants('acme'))[1]
    await waitFor(() =>
      expect(endpoints.removeSecretGrantAgent).toHaveBeenCalledWith(
        'acme',
        shared.id,
        AGENT.id,
      ),
    )
  })

  it('removes the agent from a GitHub App grant', async () => {
    vi.mocked(endpoints.removeSecretGrantAgent).mockResolvedValue(undefined)
    renderTab()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove workspace_checkout' }),
    )
    const checkout = (await endpoints.listSecretGrants('acme'))[0]
    await waitFor(() =>
      expect(endpoints.removeSecretGrantAgent).toHaveBeenCalledWith(
        'acme',
        checkout.id,
        AGENT.id,
      ),
    )
  })

  it('lets a developer of the owner team grant only grantable secrets', async () => {
    developer(['ops'])
    vi.mocked(endpoints.listSecretBindings).mockResolvedValue([
      binding('b-gh', 'secret://dev/github_app'),
      binding('b-npm', 'secret://ci/npm_token', [], { grantable: true }),
    ])
    renderTab()
    const write = (
      await screen.findByText('Push, and open pull requests and issues')
    ).closest('li')!
    // The GitHub App binding is not grantable.
    expect(within(write).queryByRole('button')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Remove secret://ci/npm_token' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Add access/ }),
    ).toBeInTheDocument()
  })

  it('gives a developer of another team no grant actions', async () => {
    developer(['web'])
    renderTab()
    expect(await screen.findByText('secret://ci/npm_token')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Remove|Add access|Grant/ }),
    ).not.toBeInTheDocument()
  })

  async function openAddAccess() {
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /Add access/ }))
    fireEvent.click(screen.getByRole('combobox', { name: 'Secret' }))
    fireEvent.click(
      await screen.findByRole('option', { name: 'secret://ci/npm_token' }),
    )
    fireEvent.click(screen.getByRole('combobox', { name: /^Purpose/ }))
  }

  it('suggests the purposes that an agent can request', async () => {
    await openAddAccess()
    const options = (await screen.findAllByRole('option')).map(
      (option) => option.textContent,
    )
    expect(options).toEqual([
      'github_read',
      'github_status',
      'github_write',
      'npm',
    ])
  })

  it('grants a suggested purpose', async () => {
    await openAddAccess()
    fireEvent.click(await screen.findByRole('option', { name: 'github_read' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({
          binding_ids: ['b-npm'],
          purposes: ['github_read'],
        }),
      ),
    )
  })

  it('grants a purpose that the user types', async () => {
    await openAddAccess()
    await userEvent.type(
      await screen.findByPlaceholderText('Search...'),
      'sentry',
    )
    fireEvent.click(screen.getByRole('option', { name: /Use “sentry”/ }))
    expect(
      screen.getByRole('combobox', { name: /^Purpose/ }),
    ).toHaveTextContent('sentry')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({
          binding_ids: ['b-npm'],
          purposes: ['sentry'],
        }),
      ),
    )
  })

  it('refuses a setup purpose that the user types', async () => {
    await openAddAccess()
    await userEvent.type(
      await screen.findByPlaceholderText('Search...'),
      'model_inference',
    )
    fireEvent.click(
      screen.getByRole('option', { name: /Use “model_inference”/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(toast.error).toHaveBeenCalledWith(
      'model_inference is for the runner only',
    )
    expect(endpoints.createSecretGrant).not.toHaveBeenCalled()
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
