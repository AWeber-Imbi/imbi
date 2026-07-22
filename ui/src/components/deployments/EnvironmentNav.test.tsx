import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
  ReleaseHistoryEntry,
} from '@/types'

import { EnvironmentNav } from './EnvironmentNav'
import type { PipelineStage } from './pipeline'

const env = (slug: string, name: string, sortOrder: number): Environment =>
  ({
    id: slug,
    label_color: '#5A89C9',
    name,
    slug,
    sort_order: sortOrder,
  }) as unknown as Environment

const current = (slug: string, tag: null | string, committish: string) =>
  ({
    ci_status: 'pass',
    current_status: 'success',
    environment: { name: slug, slug },
    external_run_url: null,
    last_event_at: '2026-06-01T00:00:00Z',
    release: {
      committish,
      created_at: '2026-06-01T00:00:00Z',
      created_by: 'gavin',
      id: `${slug}-rel`,
      links: [],
      project_id: 'p1',
      tag,
      title: tag ?? committish,
    },
  }) as CurrentReleaseEnvironment

const release = (tag: string): ReleaseHistoryEntry => ({
  ci_status: 'pass',
  sha: 'ccc333ccc333',
  short_sha: 'ccc333c',
  tag,
})

const commit = (sha: string): RecentCommit => ({
  authored_at: '2026-06-01T00:00:00Z',
  ci_status: 'pass',
  message: `change ${sha}`,
  sha,
  short_sha: sha.slice(0, 7),
})

const STAGES: PipelineStage[] = [
  {
    current: current('testing', null, 'ddd444ddd444'),
    env: env('testing', 'Testing', 1),
    kind: 'commit',
    pendingCommits: [],
    pendingReleases: [],
    rollbackTargets: [],
    upstream: null,
    upstreamCurrent: null,
  },
  {
    current: current('staging', 'v6.5.2', 'ccc333ccc333'),
    env: env('staging', 'Staging', 2),
    kind: 'promote',
    pendingCommits: Array.from({ length: 8 }, (_, i) => commit(`sha${i}aaaa`)),
    pendingReleases: [],
    rollbackTargets: [],
    upstream: env('testing', 'Testing', 1),
    upstreamCurrent: current('testing', null, 'ddd444ddd444'),
  },
  {
    current: current('production', 'v6.5.0', 'aaa111aaa111'),
    env: env('production', 'Production', 3),
    kind: 'release',
    pendingCommits: [],
    pendingReleases: [release('v6.5.2'), release('v6.5.1')],
    rollbackTargets: [],
    upstream: env('staging', 'Staging', 2),
    upstreamCurrent: current('staging', 'v6.5.2', 'ccc333ccc333'),
  },
]

const renderNav = (
  overrides: Partial<Parameters<typeof EnvironmentNav>[0]> = {},
) =>
  render(
    <EnvironmentNav
      connectLabel="Example Identity"
      isDarkMode={false}
      isSyncing={false}
      onSelect={() => {}}
      onSync={() => {}}
      readiness="connected"
      selectedSlug="staging"
      serviceIcon={null}
      serviceLabel="Example Service"
      stages={STAGES}
      {...overrides}
    />,
  )

describe('EnvironmentNav', () => {
  it('renders environments in descending sort order', () => {
    renderNav()
    const buttons = screen
      .getAllByRole('button')
      .filter((b) => /Testing|Staging|Production/.test(b.textContent ?? ''))
    expect(buttons.map((b) => b.textContent)).toEqual([
      expect.stringContaining('Production'),
      expect.stringContaining('Staging'),
      expect.stringContaining('Testing'),
    ])
  })

  it('badges pending releases and pending commits', () => {
    renderNav()
    // Production shows the newest pending release tag.
    expect(
      screen.getByTitle('Release v6.5.2 is waiting to deploy here'),
    ).toBeInTheDocument()
    // Staging shows the count of commits waiting to promote.
    expect(
      screen.getByTitle('8 commits waiting to promote here'),
    ).toBeInTheDocument()
    // Connected state names the service powering the deployment plugin.
    expect(screen.getByText('Example Service')).toBeInTheDocument()
  })

  it('invokes onSelect with the clicked environment slug', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    renderNav({ onSelect })
    await user.click(screen.getByRole('button', { name: /Production/ }))
    expect(onSelect).toHaveBeenCalledWith('production')
  })

  it('triggers the sync action and disables while syncing', async () => {
    const onSync = vi.fn()
    const user = userEvent.setup()
    renderNav({ onSync })
    await user.click(
      screen.getByRole('button', { name: 'Sync commits, tags & releases' }),
    )
    expect(onSync).toHaveBeenCalled()
  })

  it('disables the sync button while a sync is running', () => {
    renderNav({ isSyncing: true })
    expect(
      screen.getByRole('button', { name: 'Sync commits, tags & releases' }),
    ).toBeDisabled()
  })

  it('shows the connect hint when disconnected', () => {
    renderNav({ readiness: 'disconnected', selectedSlug: null })
    expect(
      screen.getByText('Connect to Example Identity to enable deployments'),
    ).toBeInTheDocument()
  })
})
