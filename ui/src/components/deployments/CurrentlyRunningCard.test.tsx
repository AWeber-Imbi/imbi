import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  ReleaseHistoryEntry,
} from '@/types'

import { CurrentlyRunningCard } from './CurrentlyRunningCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

const ENV = {
  id: 'production',
  label_color: '#C86B5E',
  name: 'Production',
  slug: 'production',
  sort_order: 3,
  url: 'https://service.example.com',
} as unknown as Environment

const CURRENT: CurrentReleaseEnvironment = {
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: 'production', slug: 'production' },
  external_run_url: null,
  last_event_at: '2026-06-01T00:00:00Z',
  performed_by: 'gavin',
  release: {
    committish: 'aaa111aaa111',
    created_at: '2026-06-01T00:00:00Z',
    created_by: 'gavin',
    id: 'rel-1',
    links: [],
    project_id: 'p1',
    tag: 'v6.5.0',
    title: 'v6.5.0',
  },
}

const ROLLBACK: ReleaseHistoryEntry = {
  author: 'gavin',
  ci_status: 'pass',
  notes_markdown: '### Fixed\n- old fix',
  published_at: '2026-05-01T00:00:00Z',
  sha: '000999000999',
  short_sha: '0009990',
  tag: 'v6.4.0',
}

const STAGE: PipelineStage = {
  current: CURRENT,
  env: ENV,
  kind: 'release',
  pendingCommits: [],
  pendingReleases: [],
  rollbackTargets: [ROLLBACK],
  upstream: null,
  upstreamCurrent: null,
}

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

describe('CurrentlyRunningCard', () => {
  it('shows the running version, deployer, and environment URL', () => {
    render(
      <CurrentlyRunningCard
        accent={null}
        actions={makeActions()}
        canTrigger
        stage={STAGE}
      />,
    )
    expect(screen.getByText('v6.5.0')).toBeInTheDocument()
    expect(screen.getByText('gavin')).toBeInTheDocument()
    expect(screen.getByText('service.example.com')).toBeInTheDocument()
  })

  it('expands a recent release into its notes', async () => {
    const user = userEvent.setup()
    render(
      <CurrentlyRunningCard
        accent={null}
        actions={makeActions()}
        canTrigger
        stage={STAGE}
      />,
    )
    await user.click(screen.getByRole('button', { name: /v6\.4\.0/ }))
    expect(screen.getByText('old fix')).toBeInTheDocument()
  })

  it('rolls back through the confirm dialog', async () => {
    const actions = makeActions()
    const user = userEvent.setup()
    render(
      <CurrentlyRunningCard
        accent={null}
        actions={actions}
        canTrigger
        stage={STAGE}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Roll back' }))
    await user.click(
      screen.getByRole('button', { name: 'Roll back to v6.4.0' }),
    )
    expect(actions.deploy).toHaveBeenCalledWith({
      action: 'deploy',
      envName: 'Production',
      envSlug: 'production',
      refLabel: 'v6.4.0',
      rollback: true,
      sha: '000999000999',
    })
  })
})
