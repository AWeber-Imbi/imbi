import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'
import type { AgentMarketplace, AgentPlatformConfigResponse } from '@/types'

import { emptyDraft, type SettingsDraft } from '../agentDraft'
import { PlatformTab } from '../PlatformTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAgentPlatformConfig: vi.fn(),
  listAgentMarketplaces: vi.fn(),
  listSecretBindings: vi.fn(),
}))

const auth = vi.hoisted(() => ({
  user: { is_admin: false, permissions: [] as string[] },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

const HEAD = 'b0b7bed9820350bb0942e32c7f00752a99ea3555'
const NOW = new Date().toISOString()

function config(): AgentPlatformConfigResponse {
  return {
    config: {
      allowed_marketplaces: ['claude-code'],
      default_plugins: [
        { marketplace: 'claude-code', plugin: 'commit-commands', sha: HEAD },
      ],
    },
    version: 2,
  } as AgentPlatformConfigResponse
}

function Harness({ initial }: { initial: SettingsDraft }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <PlatformTab
        errors={{}}
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
      plugin('remote', null),
    ],
    slug: 'claude-code',
    sync_error: null,
    synced_at: NOW,
    updated_at: NOW,
    url: 'https://github.com/anthropics/claude-code',
  }
}

describe('PlatformTab', () => {
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
    // A plugin outside the marketplace repository cannot be pinned.
    expect(screen.getByLabelText('remote')).toBeDisabled()
    expect(endpoints.listSecretBindings).not.toHaveBeenCalled()
  })

  it('adds a plugin without a sha, so the API pins it', async () => {
    render(<Harness initial={emptyDraft().settings} />)
    fireEvent.click(await screen.findByLabelText('code-review'))
    expect(JSON.parse(screen.getByTestId('plugins').textContent!)).toEqual([
      { marketplace: 'claude-code', plugin: 'code-review' },
    ])
  })

  it('offers to pin a stale plugin again', async () => {
    const initial = {
      ...emptyDraft().settings,
      plugins: [
        {
          marketplace: 'claude-code',
          plugin: 'code-review',
          sha: 'a'.repeat(40),
        },
      ],
    }
    render(<Harness initial={initial} />)
    expect(await screen.findByText('pinned aaaaaaa')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pin b0b7bed' }))
    expect(JSON.parse(screen.getByTestId('plugins').textContent!)).toEqual([
      { marketplace: 'claude-code', plugin: 'code-review' },
    ])
  })
})
