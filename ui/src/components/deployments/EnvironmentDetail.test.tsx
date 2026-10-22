import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Environment } from '@/types'

import { EnvironmentDetail } from './EnvironmentDetail'
import type { PipelineStage } from './pipeline'
import type { DeploymentActions } from './useDeploymentActions'

// Each card reports the `canTrigger` it was given, which is all the
// environment flags decide.
const { card } = vi.hoisted(() => ({
  card:
    (name: string) =>
    ({ canTrigger }: { canTrigger: boolean }) => (
      <div data-testid={name}>{String(canTrigger)}</div>
    ),
}))
vi.mock('./CommitDeployCard', () => ({ CommitDeployCard: card('commit') }))
vi.mock('./CurrentlyRunningCard', () => ({
  CurrentlyRunningCard: card('running'),
}))
vi.mock('./PendingPromoteCard', () => ({
  PendingPromoteCard: card('promote'),
}))
vi.mock('./PendingReleasesCard', () => ({
  PendingReleasesCard: card('releases'),
}))

const stage = (
  kind: PipelineStage['kind'],
  flags: { can_deploy?: boolean; can_promote?: boolean },
): PipelineStage =>
  ({
    env: { name: 'Production', slug: 'production', ...flags } as Environment,
    kind,
    pendingReleases: [],
    promotableCommits: [],
  }) as unknown as PipelineStage

const renderDetail = (s: PipelineStage) =>
  render(
    <EnvironmentDetail
      accent={null}
      actions={{} as DeploymentActions}
      canTrigger
      orgSlug="org"
      projectId="p1"
      recentCommits={[]}
      stage={s}
    />,
  )

describe('EnvironmentDetail environment flags', () => {
  it('disables direct deploys when can_deploy is false', () => {
    renderDetail(stage('commit', { can_deploy: false }))
    expect(screen.getByTestId('commit')).toHaveTextContent('false')
    expect(screen.getByText(/Direct deploys into Production/)).toBeVisible()
  })

  it('allows deploys when can_deploy is unset', () => {
    renderDetail(stage('commit', {}))
    expect(screen.getByTestId('commit')).toHaveTextContent('true')
  })

  it('disables promotion unless can_promote is true', () => {
    renderDetail(stage('promote', {}))
    expect(screen.getByTestId('promote')).toHaveTextContent('false')
    expect(screen.getByTestId('running')).toHaveTextContent('true')
    expect(screen.getByText(/Promotion into Production/)).toBeVisible()
  })

  it('allows promotion when can_promote is true', () => {
    renderDetail(stage('promote', { can_promote: true }))
    expect(screen.getByTestId('promote')).toHaveTextContent('true')
  })
})
