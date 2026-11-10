import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createSecretGrant,
  getProjectsSlim,
  getSecretResolution,
  listAgents,
  listSecretAuditEvents,
  listSecretBindings,
  listSecretGrants,
  listSecretResolutions,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { SecretsManagement } from '../SecretsManagement'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createSecretGrant: vi.fn(),
  deleteSecretGrant: vi.fn(),
  getProjectsSlim: vi.fn(),
  getSecretResolution: vi.fn(),
  listAgents: vi.fn(),
  listSecretAuditEvents: vi.fn(),
  listSecretBindings: vi.fn(),
  listSecretGrants: vi.fn(),
  listSecretResolutions: vi.fn(),
  releaseSecretResolution: vi.fn(),
  revokeSecretProviderLease: vi.fn(),
  updateSecretGrant: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    selectedOrganization: { id: 'org-1', slug: 'acme' },
  }),
}))

const renderAt = (path: string) => {
  window.history.pushState({}, '', path)
  return render(
    <Routes>
      <Route element={<SecretsManagement />} path="/admin/secrets/:slug?" />
    </Routes>,
  )
}

describe('SecretsManagement', () => {
  beforeEach(() => {
    vi.mocked(listAgents).mockResolvedValue([
      { id: 'agent-1', name: 'Release bot' } as never,
    ])
    vi.mocked(listSecretBindings).mockResolvedValue([
      {
        allowed_delivery_modes: ['environment', 'stdin'],
        id: 'binding-1',
        reference: 'secret://production/github/token',
      } as never,
    ])
    vi.mocked(getProjectsSlim).mockResolvedValue([
      { id: 'p-1', name: 'Billing', project_types: [] } as never,
      { id: 'p-2', name: 'Payments', project_types: [] } as never,
    ])
    vi.mocked(listSecretGrants).mockResolvedValue([])
    vi.mocked(createSecretGrant).mockResolvedValue({} as never)
  })

  it('creates a grant with the modes its bindings allow', async () => {
    renderAt('/admin/secrets/grants')
    fireEvent.click(await screen.findByRole('button', { name: 'New grant' }))
    fireEvent.click(await screen.findByLabelText('Release bot'))
    expect(screen.getByLabelText('File')).toBeEnabled()
    fireEvent.click(screen.getByLabelText('secret://production/github/token'))
    // The binding does not allow a file, so the grant cannot use one,
    // and the modes that it allows are selected.
    expect(screen.getByLabelText('File')).toBeDisabled()
    expect(screen.getByLabelText('Environment')).toBeChecked()
    expect(screen.getByLabelText('Stdin')).toBeChecked()
    fireEvent.click(screen.getByLabelText('Stdin'))
    fireEvent.click(screen.getByLabelText('workspace_checkout'))
    const purpose = screen.getByLabelText('Add a purpose')
    fireEvent.change(purpose, { target: { value: 'Not A Slug' } })
    fireEvent.keyDown(purpose, { key: 'Enter' })
    expect(screen.queryByLabelText('Not A Slug')).toBeNull()
    fireEvent.change(purpose, { target: { value: 'github_write' } })
    fireEvent.keyDown(purpose, { key: 'Enter' })
    expect(screen.getByLabelText('github_write')).toBeChecked()

    fireEvent.mouseDown(screen.getByRole('tab', { name: /Projects/ }))
    fireEvent.click(await screen.findByLabelText(/Selected projects/))
    fireEvent.change(screen.getByLabelText('Filter projects'), {
      target: { value: 'pay' },
    })
    expect(screen.queryByLabelText('Billing')).toBeNull()
    fireEvent.click(screen.getByLabelText('Payments'))
    fireEvent.click(screen.getByRole('button', { name: 'Create grant' }))
    await waitFor(() =>
      expect(createSecretGrant).toHaveBeenCalledWith('acme', {
        agent_ids: ['agent-1'],
        binding_ids: ['binding-1'],
        delivery_modes: ['environment'],
        max_ttl_seconds: 900,
        project_ids: ['p-2'],
        purposes: ['workspace_checkout', 'github_write'],
      }),
    )
  })

  it('shows lease revocation state, never a lease id', async () => {
    vi.mocked(listSecretResolutions).mockResolvedValue([
      {
        agent_id: 'agent-1',
        created_at: '2026-10-13T00:00:00Z',
        delivery_mode: 'environment',
        delivery_target: 'GH_TOKEN',
        expires_at: '2026-10-13T00:15:00Z',
        failure_reason: null,
        id: 'res-1',
        materialization_count: 1,
        materialization_limit: 1,
        provider_lease: {
          present: true,
          revocation_attempted_at: null,
          revocation_reason: 'unreachable',
          revocation_state: 'failed',
        },
        purpose: 'github_write',
        reference: 'secret://production/github/token',
        state: 'released',
      } as never,
    ])
    renderAt('/admin/secrets/resolutions')
    expect(
      await screen.findByRole('button', { name: 'Revoke lease' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('failed')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Release' })).toBeNull()
  })

  it('filters audit events and links to the resolution', async () => {
    vi.mocked(listSecretAuditEvents).mockResolvedValue([
      {
        actor: 'runner:1',
        at: '2026-10-13T00:00:00Z',
        event_id: 'e-1',
        purpose: 'github_write',
        reason: '',
        resolution_id: 'res-12345678',
        result: 'succeeded',
        type: 'secret_materialized',
      } as never,
    ])
    vi.mocked(getSecretResolution).mockResolvedValue({
      agent_id: 'agent-1',
      created_at: '2026-10-13T00:00:00Z',
      delivery_mode: 'environment',
      delivery_target: null,
      expires_at: '2026-10-13T00:15:00Z',
      failure_reason: null,
      id: 'res-12345678',
      materialization_count: 0,
      materialization_limit: 1,
      provider_lease: { revocation_state: 'not_applicable' },
      purpose: 'github_write',
      reference: 'secret://production/github/token',
      state: 'active',
    } as never)
    renderAt('/admin/secrets/audit')
    fireEvent.click(await screen.findByRole('combobox', { name: 'Category' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Resolutions' }))
    fireEvent.click(screen.getByRole('combobox', { name: 'Result' }))
    fireEvent.click(await screen.findByRole('option', { name: /denied/i }))
    await waitFor(() =>
      expect(listSecretAuditEvents).toHaveBeenLastCalledWith(
        'acme',
        {
          resolution_id: '',
          result: 'denied',
          type: [
            'secret_resolution_allowed',
            'secret_resolution_denied',
            'secret_resolution_released',
            'secret_resolution_expired',
            'secret_materialized',
          ],
        },
        expect.anything(),
      ),
    )
    fireEvent.click(await screen.findByRole('link', { name: 'res-1234' }))
    await waitFor(() =>
      expect(getSecretResolution).toHaveBeenCalledWith(
        'acme',
        'res-12345678',
        expect.anything(),
      ),
    )
    expect(
      await screen.findByRole('link', { name: 'History' }),
    ).toHaveAttribute('href', '/admin/secrets/audit?resolution=res-12345678')
  })

  it('lists active resolutions by default', async () => {
    vi.mocked(listSecretResolutions).mockResolvedValue([])
    renderAt('/admin/secrets/resolutions')
    expect(
      await screen.findByText('No active secret resolutions.'),
    ).toBeInTheDocument()
    expect(listSecretResolutions).toHaveBeenCalledWith(
      'acme',
      'active',
      expect.anything(),
    )
    fireEvent.click(screen.getByRole('radio', { name: /all/i }))
    await waitFor(() =>
      expect(listSecretResolutions).toHaveBeenLastCalledWith(
        'acme',
        undefined,
        expect.anything(),
      ),
    )
  })
})
