import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { AIModel, AIProvider, AIProviderDriver, Team } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAIModel: vi.fn(),
  createAIProvider: vi.fn(),
  deleteAIModel: vi.fn(),
  deleteAIProvider: vi.fn(),
  deleteAIProviderCredentials: vi.fn(),
  discoverAIModels: vi.fn(),
  importAIModels: vi.fn(),
  listAIModels: vi.fn(),
  listAIProviderDrivers: vi.fn(),
  listAIProviders: vi.fn(),
  listTeams: vi.fn(),
  setAIProviderCredentials: vi.fn(),
  updateAIModel: vi.fn(),
  updateAIProvider: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const drivers: AIProviderDriver[] = [
  {
    default_base_url: 'https://api.anthropic.com',
    description: 'Claude models from Anthropic.',
    icon: 'Sparkles',
    name: 'Anthropic',
    requires_base_url: false,
    slug: 'anthropic',
    supports_discovery: true,
    supports_iam: false,
  },
  {
    default_base_url: 'https://api.openai.com/v1',
    description: 'GPT models from OpenAI.',
    icon: 'Bot',
    name: 'OpenAI',
    requires_base_url: false,
    slug: 'openai',
    supports_discovery: true,
    supports_iam: false,
  },
]

const provider: AIProvider = {
  auth_kind: 'api_key',
  base_url: 'https://api.anthropic.com',
  credential_hint: 'abcd',
  credential_updated_at: '2026-08-01T00:00:00Z',
  description: 'Claude models from Anthropic.',
  driver: 'anthropic',
  enabled: true,
  enabled_model_count: 1,
  has_credentials: true,
  id: 'prov-1',
  is_builtin_driver: true,
  model_count: 1,
  name: 'Anthropic',
  project_id: null,
  region: null,
  slug: 'anthropic',
}

const model: AIModel = {
  access_scope: 'organization',
  allowed_teams: [],
  context_window: 200000,
  default_temperature: null,
  default_top_p: null,
  enabled: true,
  id: 'model-1',
  input_cost_per_million: 3,
  kind: 'chat',
  max_output_tokens: 8192,
  model_id: 'claude-fable-5-1',
  monthly_spend_cap: 4000,
  name: 'Claude Fable 5.1',
  output_cost_per_million: 15,
  provider_id: 'prov-1',
  provider_name: 'Anthropic',
  slug: 'claude-fable-5-1',
}

const team = { id: 'team-1', name: 'Platform', slug: 'platform' } as Team

// The section reads :slug / :action from the admin route, so the dialogs
// only open when it is mounted under that route pattern.
const mountAt = async (path: string) => {
  window.history.pushState({}, '', path)
  const { AIModelsManagement } = await import('../AIModelsManagement')
  render(
    <Routes>
      <Route
        element={<AIModelsManagement />}
        path="/admin/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('AIModelsManagement', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const endpoints = await import('@/api/endpoints')
    vi.mocked(endpoints.listAIProviderDrivers).mockResolvedValue(drivers)
    vi.mocked(endpoints.listAIProviders).mockResolvedValue([provider])
    vi.mocked(endpoints.listAIModels).mockResolvedValue([model])
    vi.mocked(endpoints.listTeams).mockResolvedValue([team])
    vi.mocked(endpoints.createAIModel).mockResolvedValue(model)
    vi.mocked(endpoints.updateAIModel).mockResolvedValue(model)
    vi.mocked(endpoints.updateAIProvider).mockResolvedValue(provider)
    vi.mocked(endpoints.deleteAIProvider).mockResolvedValue(undefined)
    vi.mocked(endpoints.setAIProviderCredentials).mockResolvedValue(provider)
    vi.mocked(endpoints.deleteAIProviderCredentials).mockResolvedValue({
      ...provider,
      auth_kind: 'none',
      credential_hint: null,
      credential_updated_at: null,
      has_credentials: false,
    })
    vi.mocked(endpoints.discoverAIModels).mockResolvedValue({
      fetched_at: '2026-09-04T00:00:00Z',
      models: [
        {
          already_configured: true,
          context_window: 200000,
          created_at: null,
          display_name: 'Claude Fable 5.1',
          max_output_tokens: 8192,
          model_id: 'claude-fable-5-1',
        },
        {
          already_configured: false,
          context_window: 200000,
          created_at: null,
          display_name: 'Claude Opus 5',
          max_output_tokens: 8192,
          model_id: 'claude-opus-5',
        },
      ],
    })
    vi.mocked(endpoints.importAIModels).mockResolvedValue({
      created: [],
      skipped: [],
    })
  })

  it('renders configured providers and unconfigured drivers as ghost rows', async () => {
    await mountAt('/admin/ai-models')

    await waitFor(() =>
      expect(screen.getByText('Anthropic')).toBeInTheDocument(),
    )
    // OpenAI has no configured provider, so it renders as a ghost row.
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
    expect(screen.getByText('Set up')).toBeInTheDocument()
    expect(screen.getByText('Key set')).toBeInTheDocument()
    expect(screen.getByText('••••abcd')).toBeInTheDocument()
    // Anthropic has credentials and a discovery-capable driver.
    expect(
      screen.getByRole('button', { name: /discover models from anthropic/i }),
    ).toBeInTheDocument()
  })

  it('lists a provider’s models when the row is expanded', async () => {
    await mountAt('/admin/ai-models')

    await waitFor(() =>
      expect(screen.getByText('Anthropic')).toBeInTheDocument(),
    )
    expect(screen.queryByText('claude-fable-5-1')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /expand anthropic/i }))

    await waitFor(() =>
      expect(screen.getByText('Claude Fable 5.1')).toBeInTheDocument(),
    )
    expect(screen.getByText('claude-fable-5-1')).toBeInTheDocument()
    expect(screen.getByText('All teams')).toBeInTheDocument()
    expect(screen.getByText('$4,000/mo')).toBeInTheDocument()
  })

  it('patches enabled when a model switch is toggled', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models')

    await waitFor(() =>
      expect(screen.getByText('Anthropic')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /expand anthropic/i }))
    await waitFor(() =>
      expect(
        screen.getByRole('switch', { name: /disable claude fable 5\.1/i }),
      ).toBeInTheDocument(),
    )

    fireEvent.click(
      screen.getByRole('switch', { name: /disable claude fable 5\.1/i }),
    )

    await waitFor(() =>
      expect(endpoints.updateAIModel).toHaveBeenCalledWith('acme', 'model-1', [
        { op: 'replace', path: '/enabled', value: false },
      ]),
    )
  })

  it('creates a model with access scope and teams from the two-step dialog', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/new-model?provider=prov-1')

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/model name or url/i), {
      target: { value: 'claude-opus-5' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() =>
      expect(screen.getByText('Allowed teams')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Platform' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create model' }))

    await waitFor(() =>
      expect(endpoints.createAIModel).toHaveBeenCalledWith(
        'acme',
        expect.objectContaining({
          access_scope: 'restricted',
          allowed_team_ids: ['team-1'],
          model_id: 'claude-opus-5',
          provider_id: 'prov-1',
        }),
      ),
    )
  })

  it('patches only the changed fields when a model is edited', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/model-1/edit')

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/display name/i), {
      target: { value: 'Fable 5.1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() =>
      expect(screen.getByLabelText(/context window/i)).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText(/context window/i), {
      target: { value: '150000' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(endpoints.updateAIModel).toHaveBeenCalledWith(
        'acme',
        'model-1',
        expect.arrayContaining([
          { op: 'replace', path: '/name', value: 'Fable 5.1' },
          { op: 'replace', path: '/context_window', value: 150000 },
        ]),
      ),
    )
    // Untouched fields must stay out of the patch.
    const ops = vi.mocked(endpoints.updateAIModel).mock.calls[0][2]
    expect(ops.map((op) => op.path).sort()).toEqual([
      '/context_window',
      '/name',
    ])
  })

  it('rejects a non-numeric entry instead of clearing it', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/model-1/edit')

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() =>
      expect(screen.getByLabelText(/context window/i)).toBeInTheDocument(),
    )

    fireEvent.change(screen.getByLabelText(/context window/i), {
      target: { value: '20k' },
    })

    await waitFor(() =>
      expect(screen.getByText('Enter a number.')).toBeInTheDocument(),
    )
    expect(screen.getByLabelText(/context window/i)).toHaveValue('20k')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    expect(endpoints.updateAIModel).not.toHaveBeenCalled()
  })

  it('deletes a model only after the confirmation is accepted', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/model-1/edit')

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete model' }),
      ).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Delete model' }))
    // The footer button only opens the confirmation.
    expect(endpoints.deleteAIModel).not.toHaveBeenCalled()

    await waitFor(() =>
      expect(screen.getByText('Delete Claude Fable 5.1?')).toBeInTheDocument(),
    )
    // Two buttons share the label; the confirming one is in the alert.
    const confirm = within(screen.getByRole('alertdialog'))
    fireEvent.click(confirm.getByRole('button', { name: 'Delete model' }))

    await waitFor(() =>
      expect(endpoints.deleteAIModel).toHaveBeenCalledWith('acme', 'model-1'),
    )
  })

  it('patches a provider from the edit-provider route', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/prov-1/edit-provider')

    await waitFor(() =>
      expect(screen.getByText('Edit Anthropic')).toBeInTheDocument(),
    )
    // The driver is fixed once models point at the provider.
    expect(screen.getByRole('combobox', { name: 'Driver' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Anthropic Production' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(endpoints.updateAIProvider).toHaveBeenCalledWith(
        'acme',
        'prov-1',
        [{ op: 'replace', path: '/name', value: 'Anthropic Production' }],
      ),
    )
  })

  it('blocks provider deletion while it still serves models', async () => {
    await mountAt('/admin/ai-models/prov-1/edit-provider')

    await waitFor(() =>
      expect(screen.getByText('Edit Anthropic')).toBeInTheDocument(),
    )
    // model_count is 1 in the fixture.
    expect(
      screen.getByRole('button', { name: 'Delete provider' }),
    ).toBeDisabled()
  })

  it('sets provider credentials from the credentials route', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/prov-1/credentials')

    await waitFor(() =>
      expect(screen.getByText('Anthropic credentials')).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText(/api key/i), {
      target: { value: 'sk-new-key' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))

    await waitFor(() =>
      expect(endpoints.setAIProviderCredentials).toHaveBeenCalledWith(
        'acme',
        'prov-1',
        'sk-new-key',
      ),
    )
  })

  it('lists discovered models and imports the ones selected', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/prov-1/discover')

    await waitFor(() =>
      expect(screen.getByText('Claude Opus 5')).toBeInTheDocument(),
    )
    expect(endpoints.discoverAIModels).toHaveBeenCalledWith('acme', 'prov-1')
    // The already-configured model is listed but cannot be selected.
    expect(screen.getByText('Already configured')).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: 'Claude Fable 5.1' }),
    ).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Claude Opus 5' }))
    fireEvent.click(screen.getByRole('button', { name: 'Import 1 model' }))

    await waitFor(() =>
      expect(endpoints.importAIModels).toHaveBeenCalledWith('acme', 'prov-1', {
        models: [
          expect.objectContaining({
            display_name: 'Claude Opus 5',
            model_id: 'claude-opus-5',
          }),
        ],
      }),
    )
  })

  it('removes provider credentials from the credentials dialog', async () => {
    const endpoints = await import('@/api/endpoints')
    await mountAt('/admin/ai-models/prov-1/credentials')

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Remove key' }),
      ).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove key' }))
    expect(endpoints.deleteAIProviderCredentials).not.toHaveBeenCalled()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove' })).toBeVisible(),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() =>
      expect(endpoints.deleteAIProviderCredentials).toHaveBeenCalledWith(
        'acme',
        'prov-1',
      ),
    )
  })
})
