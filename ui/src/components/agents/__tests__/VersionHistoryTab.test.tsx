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

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

describe('VersionHistoryTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
