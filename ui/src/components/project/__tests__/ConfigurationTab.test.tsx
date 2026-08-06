import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import {
  fetchConfigurationValues,
  listConfigurationKeys,
  setConfigurationValue,
} from '@/api/endpoints'
import { ConfigurationTab } from '@/components/project/ConfigurationTab'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { render, screen, waitFor } from '@/test/utils'
import type { ConfigKeyValueResponse, Environment } from '@/types'

vi.mock('@/api/endpoints', () => ({
  deleteConfigurationKey: vi.fn(),
  fetchConfigurationValues: vi.fn(),
  getConfigurationPrefix: vi.fn(async () => ({ prefix: 'imbi/acme/' })),
  listConfigurationKeys: vi.fn(),
  listProjectPlugins: vi.fn(async () => [
    { label: 'AWS SSM', plugin_id: 'aws', plugin_type: 'configuration' },
  ]),
  setConfigurationValue: vi.fn(() => new Promise(() => {})),
}))

const PASSWORD_KEY = 'imbi/acme/db/password'
const USER_KEY = 'imbi/acme/db/user'

const environments = [
  { name: 'Staging', slug: 'staging', sort_order: 1 },
  { name: 'Production', slug: 'production', sort_order: 2 },
] as unknown as Environment[]

const keyList = (secret = false) => [
  {
    data_type: secret ? 'secret' : 'string',
    key: PASSWORD_KEY,
    last_modified: null,
    secret,
  },
  { data_type: 'string', key: USER_KEY, last_modified: null, secret: false },
]

const value = (key: string, val: string): ConfigKeyValueResponse => ({
  data_type: 'string',
  key,
  last_modified: null,
  secret: false,
  value: val,
})

// Resolves the values query per environment from `byEnv`; a missing entry
// leaves the query pending forever.
function stubValues(
  byEnv: Record<string, (() => Promise<ConfigKeyValueResponse[]>) | undefined>,
) {
  vi.mocked(fetchConfigurationValues).mockImplementation(
    (_org, _project, _keys, params) => {
      const handler = byEnv[params?.environment ?? '']
      if (!handler) return new Promise(() => {})
      return handler()
    },
  )
}

const renderTab = () =>
  render(
    <ThemeProvider>
      <ConfigurationTab
        environments={environments}
        orgSlug="acme"
        projectId="proj-1"
      />
    </ThemeProvider>,
  )

const duplicateButton = async () =>
  await screen.findByRole('button', { name: /duplicate/i })

describe('ConfigurationTab Duplicate action', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(setConfigurationValue).mockImplementation(
      () => new Promise(() => {}) as never,
    )
    vi.mocked(listConfigurationKeys).mockImplementation(
      async () => keyList() as never,
    )
  })

  it('disables Duplicate while an environment value query is pending', async () => {
    stubValues({
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute('title', 'Values are still loading')
  })

  it('disables Duplicate when a value query rejects with 403', async () => {
    stubValues({
      production: () => Promise.reject(new ApiError(403, 'Forbidden')),
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() =>
      expect(button).toHaveAttribute(
        'title',
        'Values failed to load for Production',
      ),
    )
    expect(button).toBeDisabled()
  })

  it('disables Duplicate when the values response omits the key for an environment', async () => {
    stubValues({
      production: async () => [value(USER_KEY, 'user-prod')],
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() =>
      expect(button).toHaveAttribute(
        'title',
        'Values are unavailable for Production',
      ),
    )
    expect(button).toBeDisabled()
  })

  it('enables Duplicate once every environment value has landed, and writes each environment value on Save', async () => {
    stubValues({
      production: async () => [value(PASSWORD_KEY, 'pw-prod')],
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() => expect(button).toBeEnabled())

    const user = userEvent.setup()
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() => expect(setConfigurationValue).toHaveBeenCalledTimes(2))
    expect(setConfigurationValue).toHaveBeenCalledWith(
      'acme',
      'proj-1',
      'imbi/acme/db/',
      { data_type: 'string', secret: false, value: 'pw-staging' },
      { environment: 'staging', source: 'aws' },
    )
    expect(setConfigurationValue).toHaveBeenLastCalledWith(
      'acme',
      'proj-1',
      'imbi/acme/db/',
      { data_type: 'string', secret: false, value: 'pw-prod' },
      { environment: 'production', source: 'aws' },
    )
  })

  it('preserves an explicitly empty source value when duplicating', async () => {
    stubValues({
      production: async () => [value(PASSWORD_KEY, '')],
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() => expect(button).toBeEnabled())

    const user = userEvent.setup()
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() => expect(setConfigurationValue).toHaveBeenCalledTimes(2))
    expect(setConfigurationValue).toHaveBeenCalledWith(
      'acme',
      'proj-1',
      'imbi/acme/db/',
      { data_type: 'string', secret: false, value: 'pw-staging' },
      { environment: 'staging', source: 'aws' },
    )
    expect(setConfigurationValue).toHaveBeenCalledWith(
      'acme',
      'proj-1',
      'imbi/acme/db/',
      { data_type: 'string', secret: false, value: '' },
      { environment: 'production', source: 'aws' },
    )
  })

  it('duplicates a key whose source values are all empty', async () => {
    stubValues({
      production: async () => [value(PASSWORD_KEY, '')],
      staging: async () => [value(PASSWORD_KEY, '')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() => expect(button).toBeEnabled())

    const user = userEvent.setup()
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() => expect(setConfigurationValue).toHaveBeenCalledTimes(2))
    for (const env of ['staging', 'production']) {
      expect(setConfigurationValue).toHaveBeenCalledWith(
        'acme',
        'proj-1',
        'imbi/acme/db/',
        { data_type: 'string', secret: false, value: '' },
        { environment: env, source: 'aws' },
      )
    }
  })

  it('uses the pending type override when duplicating', async () => {
    stubValues({
      production: async () => [value(PASSWORD_KEY, 'pw-prod')],
      staging: async () => [value(PASSWORD_KEY, 'pw-staging')],
    })
    renderTab()
    const button = await duplicateButton()
    await waitFor(() => expect(button).toBeEnabled())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Secret' }))
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() =>
      expect(setConfigurationValue).toHaveBeenLastCalledWith(
        'acme',
        'proj-1',
        'imbi/acme/db/',
        { data_type: 'secret', secret: true, value: 'pw-prod' },
        { environment: 'production', source: 'aws' },
      ),
    )
  })
})
