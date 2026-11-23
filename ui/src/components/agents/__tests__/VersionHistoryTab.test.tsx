import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen, waitFor } from '@/test/utils'

import { VersionHistoryTab } from '../VersionHistoryTab'
import { agent } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteAgent: vi.fn(),
  listAgents: vi.fn(),
  listAgentVersions: vi.fn(),
  restoreAgentVersion: vi.fn(),
}))

const ADMIN = {
  is_admin: true,
  organizations: [{ organization_slug: 'acme', permissions: [] as string[] }],
  permissions: [] as string[],
  teams: [] as { organization_slug: string; team_slug: string }[],
}
const auth = vi.hoisted(() => ({ user: {} as typeof ADMIN }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

/** A user with agent:write and no agent:delete, in `team`. */
function writer(team: string) {
  auth.user = {
    is_admin: false,
    organizations: [
      { organization_slug: 'acme', permissions: ['agent:read', 'agent:write'] },
    ],
    permissions: [],
    teams: [{ organization_slug: 'acme', team_slug: team }],
  }
}

describe('VersionHistoryTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = ADMIN
    vi.mocked(endpoints.listAgentVersions).mockResolvedValue([])
  })

  it('locks delete when the agent list does not load', async () => {
    vi.mocked(endpoints.listAgents).mockRejectedValue(new Error('boom'))
    render(<VersionHistoryTab agent={agent()} orgSlug="acme" />)
    const button = screen.getByRole('button', { name: 'Delete agent' })
    expect(button).toBeDisabled()
    await waitFor(() => expect(endpoints.listAgents).toHaveBeenCalledTimes(1))
    expect(button).toBeDisabled()
  })

  it('allows delete when the agent list loads', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    render(<VersionHistoryTab agent={agent()} orgSlug="acme" />)
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete agent' }),
      ).toBeEnabled(),
    )
  })

  it('lets a member of the owner team delete without agent:delete', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    writer('platform')
    render(<VersionHistoryTab agent={agent()} orgSlug="acme" />)
    expect(
      await screen.findByRole('button', { name: 'Delete agent' }),
    ).toBeInTheDocument()
  })

  it('hides delete from another team without agent:delete', () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent()])
    writer('web')
    render(<VersionHistoryTab agent={agent()} orgSlug="acme" />)
    expect(
      screen.queryByRole('button', { name: 'Delete agent' }),
    ).not.toBeInTheDocument()
  })
})
