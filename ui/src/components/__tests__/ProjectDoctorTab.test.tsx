import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { Project } from '@/types'

import { ProjectDoctorTab } from '../ProjectDoctorTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getProjectAnalysis: vi.fn().mockResolvedValue(null),
  remediateAllAnalysisFindings: vi.fn(),
  remediateAnalysisFinding: vi.fn(),
  rescoreProject: vi.fn(),
  runProjectAnalysis: vi.fn(),
}))

const auth = vi.hoisted(() => ({
  user: { is_admin: false, permissions: [] as string[] },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const idleSync = { isSyncing: false, sync: vi.fn() }

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useCommitSync', () => ({ useCommitSync: () => idleSync }))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/usePRSync', () => ({ usePRSync: () => idleSync }))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useDeploymentResync', () => ({
  useProjectDeploymentResync: () => idleSync,
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useProjectPatch', () => ({
  useProjectPatch: () => ({ scheduleScoreRefresh: vi.fn() }),
}))

const PROJECT = { id: 'p-1', project_types: [] } as unknown as Project

describe('ProjectDoctorTab sync gating', () => {
  beforeEach(() => {
    auth.user = { is_admin: false, permissions: [] }
  })

  it('gates each sync button on the permission its endpoint checks', () => {
    auth.user.permissions = [
      'project:commits:write',
      'project:pull-requests:write',
    ]
    render(<ProjectDoctorTab project={PROJECT} />)

    expect(
      screen.getByRole('button', { name: 'Sync Commits & Tags' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync PRs' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sync Deployments' }),
    ).not.toBeInTheDocument()
  })

  it('hides commit and PR sync from deployment:write alone', () => {
    auth.user.permissions = ['project:deployment:write']
    render(<ProjectDoctorTab project={PROJECT} />)

    expect(
      screen.getByRole('button', { name: 'Sync Deployments' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sync Commits & Tags' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sync PRs' }),
    ).not.toBeInTheDocument()
  })
})
