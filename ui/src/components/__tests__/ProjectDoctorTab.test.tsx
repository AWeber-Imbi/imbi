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

interface Membership {
  organization_slug: string
  permissions: string[]
}

const auth = vi.hoisted(() => ({
  user: {
    is_admin: false,
    organizations: [] as Membership[],
    permissions: [] as string[],
  },
}))

// The sync routes check the role in the project's organization (acme)
// only, so the user holds `permissions` there and in the union.
function memberOfAcme(permissions: string[]) {
  auth.user.permissions = permissions
  auth.user.organizations = [{ organization_slug: 'acme', permissions }]
}

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
    auth.user = { is_admin: false, organizations: [], permissions: [] }
  })

  it('gates each sync button on the permission its endpoint checks', () => {
    memberOfAcme(['project:commits:write', 'project:pull-requests:write'])
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
    memberOfAcme(['project:deployment:write'])
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

  it('hides the syncs when the role in the project org lacks them', () => {
    // Developer in another org, read-only in acme: the union holds every
    // sync permission, but the routes check acme only.
    const sync = [
      'project:commits:write',
      'project:deployment:write',
      'project:pull-requests:write',
    ]
    auth.user.permissions = sync
    auth.user.organizations = [
      { organization_slug: 'acme', permissions: [] },
      { organization_slug: 'other', permissions: sync },
    ]
    render(<ProjectDoctorTab project={PROJECT} />)

    for (const name of [
      'Sync Commits & Tags',
      'Sync PRs',
      'Sync Deployments',
    ]) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })
})
