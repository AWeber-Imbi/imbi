import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { render } from '@/test/utils'
import type {
  CurrentReleaseEnvironment,
  Environment,
  RecentCommit,
} from '@/types'

import { CommitDeployCard } from './CommitDeployCard'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

const ENV = {
  id: 'testing',
  label_color: '#6B9A3F',
  name: 'Testing',
  slug: 'testing',
  sort_order: 1,
} as unknown as Environment

const commit = (sha: string, message: string): RecentCommit => ({
  author: 'kevin',
  authored_at: '2026-06-01T00:00:00Z',
  ci_status: 'pass',
  message,
  sha,
  short_sha: sha.slice(0, 7),
})

const currentFor = (committish: string): CurrentReleaseEnvironment => ({
  ci_status: 'pass',
  current_status: 'success',
  environment: { name: 'testing', slug: 'testing' },
  external_run_url: null,
  last_event_at: '2026-06-01T00:00:00Z',
  release: {
    committish,
    created_at: '2026-06-01T00:00:00Z',
    created_by: 'gavin',
    id: 'rel-1',
    links: [],
    project_id: 'p1',
    tag: null,
    title: committish,
  },
})

const makeStage = (committish: string): PipelineStage => ({
  current: currentFor(committish),
  env: ENV,
  kind: 'commit',
  pendingCommits: [],
  pendingReleases: [],
  rollbackTargets: [],
  upstream: null,
  upstreamCurrent: null,
})

const makeActions = (): DeploymentActions => ({
  deploy: vi.fn(),
  deployPending: false,
  deployPendingSha: null,
  promote: vi.fn(),
  promotePending: false,
})

const RECENT = [
  commit('aaa1111aaa1111', 'newest change'),
  commit('bbb2222bbb2222', 'middle change'),
  commit('ccc3333ccc3333', 'older change'),
]

const setup = (committish: string, recentCommits: RecentCommit[] = RECENT) =>
  render(
    <CommitDeployCard
      accent={null}
      actions={makeActions()}
      canTrigger
      recentCommits={recentCommits}
      stage={makeStage(committish)}
    />,
  )

describe('CommitDeployCard', () => {
  it('marks the deployed commit and splits Deploy/Roll back around it', () => {
    setup('bbb2222bbb2222')
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(screen.getByText('HEAD')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Deploy/ })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: /Roll back/ })).toHaveLength(1)
  })

  it('pulls the deployed commit forward when it is outside the display window', () => {
    // 30 commits in the synced history; the deployed one is the 28th —
    // beyond the 25-row display window, so it pins below a gap row.
    const many = Array.from({ length: 30 }, (_, i) =>
      commit(`sha${String(i).padStart(4, '0')}aaaa`, `commit ${i}`),
    )
    setup('sha0027aaaa', many)
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(screen.getByText('commit 27')).toBeInTheDocument()
    expect(screen.getByText('… older commits not shown')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Roll back/ })).toBeNull()
  })

  it('pins a bare-SHA row when the deployed commit is not synced at all', () => {
    setup('fff9999fff9999')
    expect(screen.getByText('deployed')).toBeInTheDocument()
    expect(
      screen.getByText('Not in the synced commit history — try a sync'),
    ).toBeInTheDocument()
  })

  it('prompts for a sync when no commits are synced', () => {
    setup('bbb2222bbb2222', [])
    expect(
      screen.getByText(
        'No synced commits yet — run a sync from the pipeline sidebar.',
      ),
    ).toBeInTheDocument()
  })
})
