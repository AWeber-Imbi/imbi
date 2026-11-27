import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { ProjectActivityLog } from '@/components/ProjectActivityLog'
import { render, screen } from '@/test/utils'
import type { Agent, OperationsLogRecord } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listAdminUsers: vi.fn(),
  listAgents: vi.fn(),
  listEnvironments: vi.fn(),
  listIntegrations: vi.fn(),
  listOperationsLog: vi.fn(),
  listPluginOpsLogTemplates: vi.fn(),
  listProjectEvents: vi.fn(),
}))

vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => true,
}))

const AGENT_ID = 'QvTsepJiJD7g-5b-K5ehP'

describe('ProjectActivityLog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listAdminUsers).mockResolvedValue([])
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([])
    vi.mocked(endpoints.listIntegrations).mockResolvedValue([])
    vi.mocked(endpoints.listPluginOpsLogTemplates).mockResolvedValue([])
    vi.mocked(endpoints.listProjectEvents).mockResolvedValue({
      entries: [],
    } as never)
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      { id: AGENT_ID, name: 'Dependency Bot', slug: 'dependency-bot' } as Agent,
    ])
    vi.mocked(endpoints.listOperationsLog).mockResolvedValue({
      entries: [
        {
          description: 'Deployed 1.2.3',
          entry_type: 'Deployed',
          environment_slug: '',
          id: 'op-1',
          occurred_at: new Date().toISOString(),
          performed_by: AGENT_ID,
          project_slug: 'webform',
          recorded_by: AGENT_ID,
        } as OperationsLogRecord,
      ],
    } as never)
  })

  it('shows the agent name for a row an agent performed', async () => {
    render(
      <ProjectActivityLog
        orgSlug="aweber"
        projectId="p1"
        projectSlug="webform"
      />,
    )

    expect(await screen.findByText('Dependency Bot')).toBeInTheDocument()
    expect(screen.queryByText(AGENT_ID)).not.toBeInTheDocument()
  })

  it('shows the agent name for an event attributed to an agent slug', async () => {
    vi.mocked(endpoints.listOperationsLog).mockResolvedValue({
      entries: [],
    } as never)
    vi.mocked(endpoints.listProjectEvents).mockResolvedValue({
      entries: [
        {
          attributed_to: 'dependency-bot',
          id: 'ev-1',
          integration: 'internal',
          metadata: {},
          payload: { field: 'status', new: 'medium', old: null },
          recorded_at: new Date().toISOString(),
          type: 'project-change',
        },
      ],
    } as never)

    render(
      <ProjectActivityLog
        orgSlug="aweber"
        projectId="p1"
        projectSlug="webform"
      />,
    )

    expect(await screen.findByText('Dependency Bot')).toBeInTheDocument()
    expect(screen.queryByText('dependency-bot')).not.toBeInTheDocument()
  })

  it('does not show an agent for a webhook sender with a matching login', async () => {
    vi.mocked(endpoints.listOperationsLog).mockResolvedValue({
      entries: [],
    } as never)
    vi.mocked(endpoints.listProjectEvents).mockResolvedValue({
      entries: [
        {
          id: 'ev-2',
          integration: 'github',
          metadata: {},
          payload: { sender: { login: 'dependency-bot' } },
          recorded_at: new Date().toISOString(),
          type: 'push',
        },
      ],
    } as never)

    render(
      <ProjectActivityLog
        orgSlug="aweber"
        projectId="p1"
        projectSlug="webform"
      />,
    )

    expect(await screen.findByText('dependency-bot')).toBeInTheDocument()
    expect(screen.queryByText('Dependency Bot')).not.toBeInTheDocument()
  })
})
