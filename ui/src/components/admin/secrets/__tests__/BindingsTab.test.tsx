import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  listSecretBindings,
  listSecretProviders,
  listTokenExchangers,
  updateSecretBinding,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { BindingsTab } from '../BindingsTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createSecretBinding: vi.fn(),
  deleteSecretBinding: vi.fn(),
  listSecretBindings: vi.fn(),
  listSecretProviders: vi.fn(),
  listTokenExchangers: vi.fn(),
  updateSecretBinding: vi.fn(),
  validateSecretBinding: vi.fn(),
}))

const usage = { app_id: '42', consumers: [], host: 'github.com' }
const key = {
  allowed_delivery_modes: ['file_descriptor'],
  allowed_delivery_targets: [],
  allowed_fields: [],
  credential_class: 'static',
  description: '',
  enabled: true,
  id: 'key-1',
  locator: { secret_id: 'imbi/key' },
  max_ttl_seconds: 900,
  provider_id: 'aws',
  provider_key_usage: usage,
  reference: 'secret://dev/github_app_key',
}
const app = {
  ...key,
  credential_class: 'dynamic',
  id: 'app-1',
  locator: { app_id: '42', private_key: 'secret://dev/github_app_key' },
  provider_id: 'gh',
  provider_key_usage: null,
  reference: 'secret://dev/github_app',
}

describe('BindingsTab', () => {
  beforeEach(() => {
    vi.mocked(listSecretBindings).mockResolvedValue([key, app] as never)
    vi.mocked(listSecretProviders).mockResolvedValue([
      { config: {}, id: 'aws', name: 'aws', type: 'aws_secrets_manager' },
      { config: {}, id: 'gh', name: 'github', type: 'github_app' },
    ] as never)
    vi.mocked(listTokenExchangers).mockResolvedValue([
      { label: 'Acme AI', target_help: '{"acme_id": "..."}', vendor: 'acme' },
    ])
    vi.mocked(updateSecretBinding).mockResolvedValue({} as never)
  })

  it('shows the target help of each installed exchanger', async () => {
    render(<BindingsTab orgSlug="acme" />)
    fireEvent.click(await screen.findByRole('button', { name: 'New binding' }))
    expect(
      await screen.findByText(
        /For Acme AI workload identity \(dynamic\): \{"acme_id": "\.\.\."\}/,
      ),
    ).toBeInTheDocument()
  })

  it('adds an App binding to the consumers of its key', async () => {
    render(<BindingsTab orgSlug="acme" />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Add as consumer' }),
    )
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: { ...usage, consumers: ['app-1'] },
      }),
    )
  })

  it('does not offer a key for a different App id', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      key,
      { ...app, locator: { ...app.locator, app_id: '7' } },
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    await screen.findAllByRole('button', { name: 'Edit' })
    expect(screen.queryByRole('button', { name: 'Add as consumer' })).toBeNull()
  })

  it('requires the key host when a consumer is set', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: null },
      app,
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    fireEvent.click(screen.getByLabelText('secret://dev/github_app'))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('edits the consumers of a key binding', async () => {
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(screen.getByLabelText(/Provider key host/)).toHaveValue('github.com')
    fireEvent.click(screen.getByLabelText('secret://dev/github_app'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: { ...usage, consumers: ['app-1'] },
      }),
    )
  })

  it('does not send an unchanged key usage in a different order', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: { app_id: '42', host: 'github.com' } },
      app,
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'new' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        description: 'new',
      }),
    )
  })

  it('offers only dynamic App bindings as consumers', async () => {
    const staticApp = {
      ...key,
      id: 'static-app',
      provider_id: 'gh',
      reference: 'secret://dev/static_app',
    }
    vi.mocked(listSecretBindings).mockResolvedValue([
      key,
      app,
      staticApp,
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(screen.getByLabelText('secret://dev/github_app')).toBeInTheDocument()
    expect(screen.queryByLabelText('secret://dev/static_app')).toBeNull()
  })

  it('offers only Apps that match the key host and App id', async () => {
    const otherApp = {
      ...app,
      id: 'other-app',
      locator: { ...app.locator, app_id: '7' },
      reference: 'secret://dev/other_app',
    }
    vi.mocked(listSecretBindings).mockResolvedValue([
      key,
      app,
      otherApp,
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(screen.getByLabelText('secret://dev/github_app')).toBeInTheDocument()
    expect(screen.queryByLabelText('secret://dev/other_app')).toBeNull()
  })
})
