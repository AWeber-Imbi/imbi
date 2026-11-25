import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type {
  SecretBinding,
  SecretGrant,
  SecretProvider,
} from '@/components/admin/secrets/types'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type {
  AgentMarketplace,
  AgentPlatformConfigResponse,
  AgentPlugin,
  CatalogServer,
} from '@/types'

import { emptyDraft, type SettingsDraft } from '../agentDraft'
import { PluginsSection } from '../PluginsSection'
import type { GrantAgent } from '../useAgentGrant'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createSecretGrant: vi.fn(),
  getAgentPlatformConfig: vi.fn(),
  listAgentMarketplaces: vi.fn(),
  listSecretBindings: vi.fn(),
  listSecretGrants: vi.fn(),
  listSecretProviders: vi.fn(),
  updateSecretGrant: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const VIEWER = { is_admin: false, permissions: [] as string[] }
const ADMIN = {
  is_admin: true,
  organizations: [{ organization_slug: 'acme', permissions: [] as string[] }],
  permissions: [] as string[],
}
const auth = vi.hoisted(() => ({ user: {} as object }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const HEAD = 'b0b7bed9820350bb0942e32c7f00752a99ea3555'
const NOW = new Date().toISOString()

const server = (name: string): CatalogServer => ({
  headers: {},
  name,
  type: 'stdio',
})

const pinned = (
  plugin: string,
  changes: Partial<AgentPlugin> = {},
): AgentPlugin => ({
  marketplace: 'claude-code',
  mcp_servers: [],
  plugin,
  server_settings: {},
  ...changes,
})

const OFF = { enabled: false, secrets: {} }

const AGENT = { id: 'agt-1', name: 'Mender', team: 'ops' }
const GRAFANA_ORIGIN = 'https://grafana.example.com'
const TOKEN = 'secret://ops/grafana'

const METRICS: CatalogServer = {
  headers: { Authorization: ['METRICS_TOKEN'] },
  name: 'metrics',
  type: 'http',
  url: 'https://metrics.example.com/mcp',
}

function binding(
  id: string,
  reference: string,
  changes: Partial<SecretBinding> = {},
): SecretBinding {
  return {
    allowed_delivery_modes: ['file_descriptor', 'environment'],
    allowed_fields: [],
    enabled: true,
    id,
    max_ttl_seconds: 3600,
    provider_id: 'p-vault',
    reference,
    ...changes,
  } as SecretBinding
}

function config(): AgentPlatformConfigResponse {
  return {
    config: {
      allowed_marketplaces: ['claude-code'],
      default_plugins: [
        pinned('commit-commands', { sha: HEAD }),
        pinned('ops-tools', {
          mcp_servers: [server('loki'), server('tempo')],
          sha: 'd'.repeat(40),
        }),
        pinned('metrics-mcp', { mcp_servers: [METRICS], sha: HEAD }),
      ],
    },
    version: 2,
  } as AgentPlatformConfigResponse
}

function grant(changes: Partial<SecretGrant>): SecretGrant {
  return {
    agent_ids: [AGENT.id],
    binding_ids: [],
    delivery_modes: ['file_descriptor'],
    enabled: true,
    id: 'g-1',
    max_ttl_seconds: 900,
    project_ids: [],
    purposes: [],
    ...changes,
  } as SecretGrant
}

function Harness({
  agent = AGENT,
  initial,
}: {
  agent?: GrantAgent | null
  initial: SettingsDraft
}) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <PluginsSection
        agent={agent}
        onChange={setValue}
        orgSlug="acme"
        value={value}
      />
      <output data-testid="plugins">{JSON.stringify(value.plugins)}</output>
    </>
  )
}

// Entries of the real marketplace of github.com/anthropics/claude-code.
function marketplace(): AgentMarketplace {
  const plugin = (name: string, path: null | string = `plugins/${name}`) => ({
    category: null,
    description: `${name} plugin`,
    mcp_servers: [] as AgentMarketplace['plugins'][number]['mcp_servers'],
    name,
    path,
    source: path ? `./${path}` : { repo: 'a/b', source: 'github' },
    version: '1.0.0',
  })
  return {
    created_at: NOW,
    created_by: 'admin',
    default_branch: 'main',
    description: null,
    head_sha: HEAD,
    id: 'm-1',
    name: 'claude-code-plugins',
    plugins: [
      plugin('code-review'),
      plugin('commit-commands'),
      plugin('feature-dev'),
      {
        ...plugin('grafana-mcp', '.'),
        mcp_servers: [
          {
            headers: { Authorization: ['GRAFANA_TOKEN'] },
            name: 'grafana',
            type: 'http',
            url: 'https://grafana.example.com/mcp',
          },
          { headers: {}, name: 'local', type: 'stdio' },
        ],
      },
      {
        ...plugin('ops-tools'),
        mcp_servers: [server('loki'), server('tempo'), server('mimir')],
      },
      { ...plugin('metrics-mcp'), mcp_servers: [METRICS] },
      {
        ...plugin('mixed'),
        mcp_servers: [
          {
            headers: { Authorization: ['PLAIN'] },
            name: 'plain',
            type: 'http',
            url: 'http://plain.example.com/mcp',
          },
          {
            headers: { Authorization: ['T'], 'X-Token': ['T'] },
            name: 'events',
            type: 'sse',
            url: 'https://events.example.com/sse',
          },
          { headers: { X: ['S'] }, name: 'shell', type: 'stdio' },
          {
            headers: { Authorization: ['USER', 'PASS'] },
            name: 'pair',
            type: 'http',
            url: 'https://pair.example.com/mcp',
          },
        ],
      },
      plugin('remote', null),
      {
        ...plugin('linked', null),
        repository_sha: 'c'.repeat(40),
        repository_url: 'https://github.com/a/linked.git',
      },
    ],
    slug: 'claude-code',
    sync_error: null,
    synced_at: NOW,
    updated_at: NOW,
    url: 'https://github.com/anthropics/claude-code',
  }
}

function plugins() {
  return JSON.parse(screen.getByTestId('plugins').textContent!)
}

function provider(id: string, type: string): SecretProvider {
  return { enabled: true, id, type } as SecretProvider
}

function withPlugins(...entries: AgentPlugin[]): SettingsDraft {
  return { ...emptyDraft().settings, plugins: entries }
}

describe('PluginsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = VIEWER
    vi.mocked(endpoints.getAgentPlatformConfig).mockResolvedValue(config())
    vi.mocked(endpoints.listAgentMarketplaces).mockResolvedValue([
      marketplace(),
    ])
  })

  it('lists the plugins of the allowed marketplaces', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    expect(await screen.findByText('code-review')).toBeInTheDocument()
    expect(screen.getByText('feature-dev')).toBeInTheDocument()
    // A default plugin is on and cannot be turned off.
    expect(screen.getByLabelText('commit-commands')).toBeDisabled()
    // An external plugin without a resolved commit is not shown.
    expect(screen.queryByLabelText('remote')).not.toBeInTheDocument()
    expect(screen.getByLabelText('linked')).toBeEnabled()
  })

  it('shows an unusable plugin that is a default', async () => {
    const withRemote = config()
    withRemote.config.default_plugins.push(pinned('remote'))
    vi.mocked(endpoints.getAgentPlatformConfig).mockResolvedValue(withRemote)
    render(<Harness initial={emptyDraft().settings} />)
    expect(await screen.findByLabelText('remote')).toBeChecked()
  })

  it('lists the MCP servers that a plugin brings', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    const servers = await screen.findByRole('list', {
      name: 'MCP servers of grafana-mcp',
    })
    const items = within(servers).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    const [grafana, local] = items
    expect(within(grafana).getByText('grafana')).toBeInTheDocument()
    expect(
      within(grafana).getByText('https://grafana.example.com/mcp'),
    ).toBeInTheDocument()
    expect(within(local).getByText('local')).toBeInTheDocument()
    expect(within(local).getByText('stdio')).toBeInTheDocument()
    expect(
      screen.queryByRole('list', { name: 'MCP servers of code-review' }),
    ).not.toBeInTheDocument()
  })

  it('adds a plugin without a sha, so the API pins it', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    fireEvent.click(await screen.findByLabelText('code-review'))
    expect(plugins()).toEqual([pinned('code-review')])
  })

  it('offers to pin a stale plugin again', async () => {
    const initial = withPlugins(
      pinned('grafana-mcp', {
        mcp_servers: [server('grafana')],
        server_settings: { grafana: OFF },
        sha: 'a'.repeat(40),
      }),
    )
    render(<Harness initial={initial} />)
    expect(await screen.findByText('pinned aaaaaaa')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pin b0b7bed' }))
    expect(plugins()).toEqual([
      pinned('grafana-mcp', { server_settings: { grafana: OFF } }),
    ])
  })

  it('offers to pin an external plugin that moved', async () => {
    const initial = withPlugins(
      pinned('linked', {
        sha: 'c'.repeat(40),
        url: 'https://github.com/a/old.git',
      }),
    )
    render(<Harness initial={initial} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Pin ccccccc' }))
    expect(plugins()).toEqual([pinned('linked')])
  })

  it('turns a server of an agent plugin off and on', async () => {
    render(<Harness initial={withPlugins(pinned('grafana-mcp'))} />)
    const grafana = await screen.findByLabelText(
      'grafana-mcp MCP server grafana',
    )
    expect(grafana).toBeChecked()
    fireEvent.click(grafana)
    expect(plugins()).toEqual([
      pinned('grafana-mcp', { server_settings: { grafana: OFF } }),
    ])
    fireEvent.click(grafana)
    expect(plugins()).toEqual([pinned('grafana-mcp')])
    expect(screen.queryByText(/^Servers at/)).not.toBeInTheDocument()
  })

  it('locks the servers of a plugin that is off', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    const grafana = await screen.findByLabelText(
      'grafana-mcp MCP server grafana',
    )
    expect(grafana).toBeDisabled()
    expect(grafana).not.toBeChecked()
  })

  it('turns off a server of a default plugin with an agent entry', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    const servers = await screen.findByRole('list', {
      name: 'MCP servers of ops-tools',
    })
    expect(within(servers).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByText('mimir')).not.toBeInTheDocument()
    const loki = screen.getByLabelText('ops-tools MCP server loki')
    expect(loki).toBeEnabled()
    fireEvent.click(loki)
    expect(plugins()).toEqual([
      pinned('ops-tools', { server_settings: { loki: OFF } }),
    ])
    fireEvent.click(loki)
    expect(plugins()).toEqual([])
  })

  it('keeps the entry of a default plugin with another setting', async () => {
    const initial = withPlugins(
      pinned('ops-tools', { server_settings: { loki: OFF, tempo: OFF } }),
    )
    render(<Harness initial={initial} />)
    fireEvent.click(await screen.findByLabelText('ops-tools MCP server loki'))
    expect(plugins()).toEqual([
      pinned('ops-tools', { server_settings: { tempo: OFF } }),
    ])
  })

  it('hides the pin of a default plugin', async () => {
    const initial = withPlugins(
      pinned('ops-tools', {
        server_settings: { loki: OFF },
        sha: 'e'.repeat(40),
      }),
    )
    render(<Harness initial={initial} />)
    expect(
      await screen.findByLabelText('ops-tools MCP server loki'),
    ).not.toBeChecked()
    expect(screen.queryByText('pinned eeeeeee')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /^Pin / }),
    ).not.toBeInTheDocument()
  })

  it('lists a setting for a server that the plugin no longer has', async () => {
    const initial = withPlugins(
      pinned('grafana-mcp', {
        mcp_servers: [server('grafana')],
        server_settings: { gone: OFF, grafana: OFF },
        sha: HEAD,
      }),
    )
    render(<Harness initial={initial} />)
    const gone = await screen.findByRole('list', {
      name: 'Settings of MCP servers no longer in grafana-mcp',
    })
    expect(within(gone).getByText('gone')).toBeInTheDocument()
    expect(
      screen.queryByLabelText('grafana-mcp MCP server local'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/^Servers at/)).not.toBeInTheDocument()
    expect(
      within(gone).getByText('no longer in this plugin'),
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove the setting of gone' }),
    )
    expect(plugins()).toEqual([
      pinned('grafana-mcp', {
        mcp_servers: [server('grafana')],
        server_settings: { grafana: OFF },
        sha: HEAD,
      }),
    ])
  })

  it('shows the catalog servers for a pin with no saved list', async () => {
    const initial = withPlugins(pinned('grafana-mcp', { sha: 'a'.repeat(40) }))
    render(<Harness initial={initial} />)
    expect(
      await screen.findByText('Servers at b0b7bed. This agent runs aaaaaaa.'),
    ).toBeInTheDocument()
    expect(
      screen.getByLabelText('grafana-mcp MCP server local'),
    ).toBeInTheDocument()
  })

  describe('header secrets', () => {
    const PICKER = 'grafana-mcp grafana header GRAFANA_TOKEN'
    const MULTI = 'secret://ops/multi#token'

    beforeEach(() => {
      auth.user = ADMIN
      vi.mocked(endpoints.listSecretProviders).mockResolvedValue([
        provider('p-vault', 'vault'),
        provider('p-gh', 'github_app'),
        { ...provider('p-off', 'vault'), enabled: false },
      ])
      vi.mocked(endpoints.listSecretBindings).mockResolvedValue([
        binding('b-graf', TOKEN),
        binding('b-multi', 'secret://ops/multi', {
          allowed_fields: ['token'],
        }),
        binding('b-gh', 'secret://dev/github_app', { provider_id: 'p-gh' }),
        binding('b-env', 'secret://ops/env_only', {
          allowed_delivery_modes: ['environment'],
        }),
        binding('b-off', 'secret://ops/off_provider', {
          provider_id: 'p-off',
        }),
      ])
      vi.mocked(endpoints.listSecretGrants).mockResolvedValue([])
      vi.mocked(endpoints.createSecretGrant).mockResolvedValue(
        grant({}) as never,
      )
      vi.mocked(endpoints.updateSecretGrant).mockResolvedValue(
        grant({}) as never,
      )
    })

    async function picker(name = PICKER) {
      const trigger = await screen.findByRole('combobox', { name })
      await waitFor(() => expect(trigger).toBeEnabled())
      return trigger
    }

    async function pick(option: string, name = PICKER) {
      fireEvent.click(await picker(name))
      fireEvent.click(await screen.findByRole('option', { name: option }))
    }

    function relayed(secrets: Record<string, string>, origin = GRAFANA_ORIGIN) {
      return { enabled: true, origin, secrets }
    }

    function grafana(setting?: object): SettingsDraft {
      return withPlugins(
        pinned('grafana-mcp', {
          server_settings: setting ? { grafana: setting } : {},
        }),
      )
    }

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
              'secret_provider:read',
            ],
          },
        ],
        permissions: [],
        teams: teams.map((team) => ({
          organization_slug: 'acme',
          team_slug: team,
        })),
      }
    }

    function noGrantCalls() {
      expect(endpoints.createSecretGrant).not.toHaveBeenCalled()
      expect(endpoints.updateSecretGrant).not.toHaveBeenCalled()
    }

    it('maps a header variable to a secret and its origin', async () => {
      render(<Harness initial={grafana()} />)
      await pick(TOKEN)
      expect(plugins()).toEqual([
        pinned('grafana-mcp', {
          server_settings: { grafana: relayed({ GRAFANA_TOKEN: TOKEN }) },
        }),
      ])
    })

    it('creates an mcp_header grant for a picked secret', async () => {
      render(<Harness initial={grafana()} />)
      await pick(TOKEN)
      await waitFor(() =>
        expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
          'acme',
          expect.objectContaining({
            agent_ids: [AGENT.id],
            binding_ids: ['b-graf'],
            delivery_modes: ['file_descriptor'],
            purposes: ['mcp_header'],
          }),
        ),
      )
    })

    it('adds mcp_header to the agent grant of the secret', async () => {
      vi.mocked(endpoints.listSecretGrants).mockResolvedValue([
        grant({ binding_ids: ['b-graf'], purposes: ['model_inference'] }),
      ])
      render(<Harness initial={grafana()} />)
      await pick(TOKEN)
      await waitFor(() =>
        expect(endpoints.updateSecretGrant).toHaveBeenCalledWith(
          'acme',
          'g-1',
          { purposes: ['model_inference', 'mcp_header'] },
        ),
      )
      expect(endpoints.createSecretGrant).not.toHaveBeenCalled()
    })

    it('adds no grant when one already allows mcp_header', async () => {
      vi.mocked(endpoints.listSecretGrants).mockResolvedValue([
        grant({ binding_ids: ['b-graf'], purposes: ['mcp_header'] }),
      ])
      render(<Harness initial={grafana()} />)
      await pick(TOKEN)
      expect(await screen.findByLabelText('Granted')).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: 'Grant' }),
      ).not.toBeInTheDocument()
      noGrantCalls()
    })

    it('does not count a grant for some projects as covering', async () => {
      vi.mocked(endpoints.listSecretGrants).mockResolvedValue([
        grant({
          binding_ids: ['b-graf'],
          project_ids: ['p-1'],
          purposes: ['mcp_header'],
        }),
      ])
      render(<Harness initial={grafana()} />)
      await pick(TOKEN)
      await waitFor(() =>
        expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
          'acme',
          expect.objectContaining({
            binding_ids: ['b-graf'],
            project_ids: [],
            purposes: ['mcp_header'],
          }),
        ),
      )
      expect(endpoints.updateSecretGrant).not.toHaveBeenCalled()
    })

    it('locks the pickers until the grants load', async () => {
      vi.mocked(endpoints.listSecretGrants).mockReturnValue(
        new Promise(() => {}),
      )
      render(<Harness initial={grafana()} />)
      const trigger = await screen.findByRole('combobox', { name: PICKER })
      await waitFor(() =>
        expect(endpoints.listSecretBindings).toHaveBeenCalled(),
      )
      expect(trigger).toBeDisabled()
      fireEvent.click(trigger)
      expect(screen.queryByRole('option')).not.toBeInTheDocument()
      noGrantCalls()
    })

    it('says which permissions picking secrets needs', async () => {
      developer(['ops'])
      const user = auth.user as { organizations: { permissions: string[] }[] }
      user.organizations[0].permissions = ['secret_binding:read']
      render(<Harness initial={grafana()} />)
      const servers = await screen.findByRole('list', {
        name: 'MCP servers of grafana-mcp',
      })
      expect(
        within(servers).getByText(/need .*secret_provider:read to pick/),
      ).toBeInTheDocument()
      expect(screen.getByRole('combobox', { name: PICKER })).toBeDisabled()
    })

    it('offers only bindings that can fill a header', async () => {
      render(<Harness initial={grafana()} />)
      fireEvent.click(await picker())
      const options = (await screen.findAllByRole('option')).map(
        (option) => option.textContent,
      )
      expect(options).toEqual(['No secret', TOKEN, MULTI])
    })

    it('grants a saved secret that no grant allows', async () => {
      render(<Harness initial={grafana(relayed({ GRAFANA_TOKEN: MULTI }))} />)
      expect(await screen.findByLabelText('Not granted')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Grant' }))
      await waitFor(() =>
        expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
          'acme',
          expect.objectContaining({
            binding_ids: ['b-multi'],
            purposes: ['mcp_header'],
          }),
        ),
      )
    })

    it('keeps a saved secret that is no longer offered', async () => {
      const gone = 'secret://ops/gone'
      render(<Harness initial={grafana(relayed({ GRAFANA_TOKEN: gone }))} />)
      expect(await picker()).toHaveTextContent(gone)
      expect(
        screen.getByText('This secret cannot fill a header. Pick another.'),
      ).toBeInTheDocument()
    })

    it('does not flag a saved secret before the bindings load', async () => {
      vi.mocked(endpoints.listSecretBindings).mockReturnValue(
        new Promise(() => {}),
      )
      const gone = 'secret://ops/gone'
      render(<Harness initial={grafana(relayed({ GRAFANA_TOKEN: gone }))} />)
      expect(
        await screen.findByRole('combobox', { name: PICKER }),
      ).toHaveTextContent(gone)
      expect(screen.queryByText(/cannot fill a header/)).not.toBeInTheDocument()
    })

    describe('a user without binding write', () => {
      it('maps but does not grant for an agent of another team', async () => {
        developer(['web'])
        vi.mocked(endpoints.listSecretBindings).mockResolvedValue([
          binding('b-graf', TOKEN, { grantable: true }),
        ])
        render(<Harness initial={grafana()} />)
        await pick(TOKEN)
        expect(plugins()[0].server_settings.grafana).toEqual(
          relayed({ GRAFANA_TOKEN: TOKEN }),
        )
        expect(await screen.findByLabelText('Not granted')).toBeInTheDocument()
        expect(
          screen.queryByRole('button', { name: 'Grant' }),
        ).not.toBeInTheDocument()
        noGrantCalls()
      })

      it('does not grant a binding that is not grantable', async () => {
        developer(['ops'])
        render(<Harness initial={grafana()} />)
        await pick(TOKEN)
        expect(await screen.findByLabelText('Not granted')).toBeInTheDocument()
        expect(
          screen.queryByRole('button', { name: 'Grant' }),
        ).not.toBeInTheDocument()
        noGrantCalls()
      })

      it('grants a grantable binding to an agent of the team', async () => {
        developer(['ops'])
        vi.mocked(endpoints.listSecretBindings).mockResolvedValue([
          binding('b-graf', TOKEN, { grantable: true }),
        ])
        render(<Harness initial={grafana()} />)
        await pick(TOKEN)
        await waitFor(() =>
          expect(endpoints.createSecretGrant).toHaveBeenCalledWith(
            'acme',
            expect.objectContaining({ binding_ids: ['b-graf'] }),
          ),
        )
      })
    })

    it('maps a secret for a new agent without a grant', async () => {
      render(<Harness agent={null} initial={grafana()} />)
      await pick(TOKEN)
      expect(plugins()[0].server_settings.grafana).toEqual(
        relayed({ GRAFANA_TOKEN: TOKEN }),
      )
      expect(screen.queryByLabelText(/^(Not )?[Gg]ranted$/)).toBeNull()
      noGrantCalls()
    })

    it('hides secrets picked for another origin', async () => {
      const moved = relayed(
        { GRAFANA_TOKEN: 'secret://ops/old' },
        'https://old.example.com',
      )
      render(<Harness initial={grafana(moved)} />)
      expect(
        await screen.findByText(
          /now at https:\/\/grafana\.example\.com\/mcp, not at https:\/\/old\.example\.com/,
        ),
      ).toBeInTheDocument()
      expect(await picker()).toHaveTextContent('No secret')
    })

    it('drops the secrets of the old origin on a new pick', async () => {
      const moved = relayed(
        { GRAFANA_TOKEN: 'secret://ops/old', OTHER: TOKEN },
        'https://old.example.com',
      )
      render(<Harness initial={grafana(moved)} />)
      await pick(TOKEN)
      expect(plugins()[0].server_settings.grafana).toEqual(
        relayed({ GRAFANA_TOKEN: TOKEN }),
      )
      expect(screen.queryByText(/Pick its secrets again/)).toBeNull()
    })

    it('removes the secrets of a server that moved', async () => {
      const moved = relayed({ GRAFANA_TOKEN: TOKEN }, 'https://old.example.com')
      render(<Harness initial={grafana(moved)} />)
      fireEvent.click(
        await screen.findByRole('button', { name: 'Remove the secrets' }),
      )
      expect(plugins()).toEqual([pinned('grafana-mcp')])
      expect(screen.queryByText(/Pick its secrets again/)).toBeNull()
    })

    it('keeps a moved server off when its secrets are removed', async () => {
      const moved = {
        ...relayed({ GRAFANA_TOKEN: TOKEN }, 'https://old.example.com'),
        enabled: false,
      }
      render(<Harness initial={grafana(moved)} />)
      fireEvent.click(
        await screen.findByRole('button', { name: 'Remove the secrets' }),
      )
      expect(plugins()[0].server_settings.grafana).toEqual(OFF)
    })

    it('keeps the secrets of a server that is turned off and on', async () => {
      render(<Harness initial={grafana(relayed({ GRAFANA_TOKEN: TOKEN }))} />)
      const checkbox = await screen.findByLabelText(
        'grafana-mcp MCP server grafana',
      )
      fireEvent.click(checkbox)
      expect(plugins()[0].server_settings.grafana).toEqual({
        ...relayed({ GRAFANA_TOKEN: TOKEN }),
        enabled: false,
      })
      fireEvent.click(checkbox)
      expect(plugins()[0].server_settings.grafana).toEqual(
        relayed({ GRAFANA_TOKEN: TOKEN }),
      )
    })

    it('drops the setting when its last secret is cleared', async () => {
      render(<Harness initial={grafana(relayed({ GRAFANA_TOKEN: TOKEN }))} />)
      await pick('No secret')
      expect(plugins()).toEqual([pinned('grafana-mcp')])
      noGrantCalls()
    })

    it('keeps the other secrets when one is cleared', async () => {
      const origin = 'https://pair.example.com'
      const initial = withPlugins(
        pinned('mixed', {
          server_settings: {
            pair: relayed({ PASS: MULTI, USER: TOKEN }, origin),
          },
        }),
      )
      render(<Harness initial={initial} />)
      await pick('No secret', 'mixed pair header USER')
      expect(plugins()[0].server_settings.pair).toEqual(
        relayed({ PASS: MULTI }, origin),
      )
    })

    it('shows a picker only for each header variable of a remote https server', async () => {
      render(<Harness initial={withPlugins(pinned('mixed'))} />)
      expect(
        await screen.findAllByRole('combobox', { name: /^mixed events / }),
      ).toHaveLength(1)
      expect(
        screen.getByRole('combobox', { name: 'mixed events header T' }),
      ).toBeInTheDocument()
      expect(
        screen.getByText('Imbi sends header secrets only to an https URL.'),
      ).toBeInTheDocument()
      expect(
        screen.queryByRole('combobox', { name: /^mixed (plain|shell) / }),
      ).not.toBeInTheDocument()
    })

    it('adds an entry for a secret of a default plugin', async () => {
      const name = 'metrics-mcp metrics header METRICS_TOKEN'
      render(<Harness initial={emptyDraft().settings} />)
      await pick(TOKEN, name)
      expect(plugins()).toEqual([
        pinned('metrics-mcp', {
          server_settings: {
            metrics: relayed(
              { METRICS_TOKEN: TOKEN },
              'https://metrics.example.com',
            ),
          },
        }),
      ])
      await pick('No secret', name)
      expect(plugins()).toEqual([])
    })

    it('locks the pickers of a plugin that is off', async () => {
      render(<Harness initial={emptyDraft().settings} />)
      await waitFor(() =>
        expect(endpoints.listSecretProviders).toHaveBeenCalled(),
      )
      expect(
        await screen.findByRole('combobox', { name: PICKER }),
      ).toBeDisabled()
    })

    it('locks the pickers of a server that is off', async () => {
      render(<Harness initial={grafana()} />)
      const trigger = await picker()
      const checkbox = screen.getByLabelText('grafana-mcp MCP server grafana')
      fireEvent.click(checkbox)
      expect(trigger).toBeDisabled()
      fireEvent.click(checkbox)
      expect(trigger).toBeEnabled()
    })

    it('asks for a new pin before secrets on a pin without servers', async () => {
      const initial = withPlugins(pinned('grafana-mcp', { sha: HEAD }))
      render(<Harness initial={initial} />)
      expect(
        await screen.findByText(
          'Pin the plugin again to pick secrets for its servers.',
        ),
      ).toBeInTheDocument()
      expect(
        screen.queryByRole('combobox', { name: PICKER }),
      ).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Pin b0b7bed' }))
      expect(plugins()).toEqual([pinned('grafana-mcp')])
    })
  })
})
