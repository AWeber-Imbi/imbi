import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  listSecretBindings,
  listSecretProviders,
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
      { id: 'aws', name: 'aws', type: 'aws_secrets_manager' },
      { id: 'gh', name: 'github', type: 'github_app' },
    ] as never)
    vi.mocked(updateSecretBinding).mockResolvedValue({} as never)
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

  it('edits the consumers of a key binding', async () => {
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(screen.getByLabelText('Provider key host')).toHaveValue('github.com')
    fireEvent.click(screen.getByLabelText('secret://dev/github_app'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: { ...usage, consumers: ['app-1'] },
      }),
    )
  })
})
