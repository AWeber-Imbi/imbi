import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import {
  checkSecretLocator,
  createSecretBinding,
  listSecretBindings,
  listSecretProviders,
  listSecretProviderTypes,
  updateSecretBinding,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { BindingsTab } from '../BindingsTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  checkSecretLocator: vi.fn(),
  createSecretBinding: vi.fn(),
  deleteSecretBinding: vi.fn(),
  listSecretBindings: vi.fn(),
  listSecretProviders: vi.fn(),
  listSecretProviderTypes: vi.fn(),
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
    vi.mocked(updateSecretBinding).mockResolvedValue({} as never)
    vi.mocked(checkSecretLocator).mockResolvedValue(undefined)
    vi.mocked(listSecretProviderTypes).mockResolvedValue([])
  })

  /** Save waits for the locator check. */
  const save = async () => {
    const button = screen.getByRole('button', { name: 'Save' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
  }

  it('shows why the locator is not valid and blocks the save', async () => {
    vi.mocked(checkSecretLocator).mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: {
          error: 'invalid_configuration',
          message: 'secret_id is required',
        },
      }),
    )
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(await screen.findByText('secret_id is required')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(checkSecretLocator).toHaveBeenCalledWith('acme', {
      credential_class: 'static',
      locator: { secret_id: 'imbi/key' },
      provider_id: 'aws',
    })
    fireEvent.change(screen.getByLabelText(/Locator/), {
      target: { value: '{"secret_id": ' },
    })
    expect(
      await screen.findByText('The locator is not valid JSON'),
    ).toBeInTheDocument()
  })

  it('draws the locator fields from the provider schema', async () => {
    vi.mocked(listSecretProviderTypes).mockResolvedValue([
      {
        capabilities: [],
        credential_classes: ['static', 'rotated'],
        label: 'AWS Secrets Manager',
        locator_schema: {
          properties: {
            secret_id: {
              description: 'Name or ARN.',
              title: 'Secret ID',
              type: 'string',
            },
            version_stage: {
              anyOf: [{ type: 'string' }, { type: 'null' }],
              title: 'Version stage',
            },
          },
          required: ['secret_id'],
        },
        type: 'aws_secrets_manager',
      },
    ])
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    const secretId = await screen.findByLabelText(/Secret ID/)
    expect(secretId).toHaveValue('imbi/key')
    expect(screen.getByRole('radio', { name: 'Dynamic' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Version stage/), {
      target: { value: 'AWSPREVIOUS' },
    })
    await waitFor(() =>
      expect(checkSecretLocator).toHaveBeenCalledWith('acme', {
        credential_class: 'static',
        locator: { secret_id: 'imbi/key', version_stage: 'AWSPREVIOUS' },
        provider_id: 'aws',
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit as JSON' }))
    expect(screen.getByLabelText(/Locator/)).toHaveValue(
      JSON.stringify(
        { secret_id: 'imbi/key', version_stage: 'AWSPREVIOUS' },
        null,
        2,
      ),
    )
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

  it('takes the key host and App id from a ticked consumer', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: null },
      app,
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    fireEvent.click(screen.getByLabelText('secret://dev/github_app'))
    expect(screen.getByLabelText(/Provider key App id/)).toHaveValue('42')
    expect(screen.getByLabelText(/Provider key App id/)).toHaveAttribute(
      'readonly',
    )
    expect(
      screen.getByRole('combobox', { name: 'Provider key host' }),
    ).toBeDisabled()
    await save()
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: { ...usage, consumers: ['app-1'] },
      }),
    )
  })

  it('requires the key App id when a host is picked', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: null },
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    fireEvent.click(screen.getByRole('combobox', { name: 'Provider key host' }))
    fireEvent.click(await screen.findByRole('option', { name: 'github.com' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('edits the consumers of a key binding', async () => {
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(
      screen.getByRole('combobox', { name: 'Provider key host' }),
    ).toHaveTextContent('github.com')
    fireEvent.click(screen.getByLabelText('secret://dev/github_app'))
    await save()
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
    fireEvent.change(screen.getByLabelText(/Description/), {
      target: { value: 'new' },
    })
    await save()
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        description: 'new',
      }),
    )
  })

  it('drops saved consumers of deleted bindings', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: { ...usage, consumers: ['gone'] } },
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    expect(
      screen.getByRole('combobox', { name: 'Provider key host' }),
    ).toBeEnabled()
    await save()
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: usage,
      }),
    )
  })

  it('clears the key usage when the host is set to none', async () => {
    vi.mocked(listSecretBindings).mockResolvedValue([key] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    fireEvent.click(screen.getByRole('combobox', { name: 'Provider key host' }))
    fireEvent.click(await screen.findByRole('option', { name: 'None' }))
    fireEvent.change(screen.getByLabelText(/Provider key App id/), {
      target: { value: '' },
    })
    await save()
    await waitFor(() =>
      expect(updateSecretBinding).toHaveBeenCalledWith('acme', 'key-1', {
        provider_key_usage: null,
      }),
    )
  })

  it('keeps a free-text host when no App provider exists', async () => {
    vi.mocked(listSecretProviders).mockResolvedValue([
      { config: {}, id: 'aws', name: 'aws', type: 'aws_secrets_manager' },
    ] as never)
    vi.mocked(listSecretBindings).mockResolvedValue([
      { ...key, provider_key_usage: null },
    ] as never)
    render(<BindingsTab orgSlug="acme" />)
    const edits = await screen.findAllByRole('button', { name: 'Edit' })
    fireEvent.click(edits[0])
    fireEvent.change(screen.getByLabelText(/Provider key host/), {
      target: { value: 'g' },
    })
    expect(screen.getByLabelText(/Provider key host/)).toHaveValue('g')
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

  it('creates a binding from the reference path and tags', async () => {
    vi.mocked(createSecretBinding).mockResolvedValue({} as never)
    render(<BindingsTab orgSlug="acme" />)
    fireEvent.click(await screen.findByRole('button', { name: 'New binding' }))
    fireEvent.change(screen.getByLabelText(/Reference/), {
      target: { value: 'dev/app_db' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: 'Provider' }))
    fireEvent.click(await screen.findByRole('option', { name: /aws/ }))
    fireEvent.change(screen.getByLabelText(/Locator/), {
      target: { value: '{"secret_id": "dev/app_db"}' },
    })
    const fields = screen.getByLabelText(/Allowed fields/)
    fireEvent.change(fields, { target: { value: 'username' } })
    fireEvent.keyDown(fields, { key: 'Enter' })
    fireEvent.click(screen.getByLabelText('Environment'))
    expect(
      screen.getByText(/reads from aws, fields username/),
    ).toBeInTheDocument()
    const create = screen.getByRole('button', { name: 'Create binding' })
    await waitFor(() => expect(create).toBeEnabled())
    fireEvent.click(create)
    await waitFor(() =>
      expect(createSecretBinding).toHaveBeenCalledWith('acme', {
        allowed_delivery_modes: ['environment'],
        allowed_fields: ['username'],
        credential_class: 'static',
        locator: { secret_id: 'dev/app_db' },
        max_ttl_seconds: 900,
        provider_id: 'aws',
        reference: 'secret://dev/app_db',
      }),
    )
  })
})
