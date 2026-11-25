import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, within } from '@/test/utils'
import type {
  AgentMarketplace,
  AgentPlatformConfigResponse,
  AgentPlugin,
  CatalogServer,
} from '@/types'

import { emptyDraft, type SettingsDraft } from '../agentDraft'
import { PluginsSection } from '../PluginsSection'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAgentPlatformConfig: vi.fn(),
  listAgentMarketplaces: vi.fn(),
}))

const auth = vi.hoisted(() => ({
  user: { is_admin: false, permissions: [] as string[] },
}))

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

const OFF = { enabled: false }

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
      ],
    },
    version: 2,
  } as AgentPlatformConfigResponse
}

function Harness({ initial }: { initial: SettingsDraft }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <PluginsSection onChange={setValue} orgSlug="acme" value={value} />
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

function withPlugins(...entries: AgentPlugin[]): SettingsDraft {
  return { ...emptyDraft().settings, plugins: entries }
}

describe('PluginsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    // The servers of the default's pin, not of the catalog head.
    expect(within(servers).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByText('mimir')).not.toBeInTheDocument()
    const loki = screen.getByLabelText('ops-tools MCP server loki')
    expect(loki).toBeEnabled()
    fireEvent.click(loki)
    expect(plugins()).toEqual([
      pinned('ops-tools', { server_settings: { loki: OFF } }),
    ])
    // Its last setting removed, the entry goes, so the plugin is not
    // added to the agent.
    fireEvent.click(loki)
    expect(plugins()).toEqual([])
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
      name: 'Turned-off MCP servers no longer in grafana-mcp',
    })
    expect(within(gone).getByText('gone')).toBeInTheDocument()
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
})
