import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { Agent, OperationsLogRecord } from '@/types'

import { OperationsLogStreamRow } from '../OperationsLogStreamRow'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getOperationsLogEntry: vi.fn(),
  listPluginOpsLogTemplates: vi.fn(async () => []),
}))

vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

const AGENT_ID = 'QvTsepJiJD7g-5b-K5ehP'

describe('OperationsLogStreamRow', () => {
  it('shows the agent mark and name for an agent performer', () => {
    const agent = { icon: null, id: AGENT_ID, name: 'Dependency Bot' } as Agent
    const entry = {
      description: 'Deployed 1.2.3',
      entry_type: 'Deployed',
      environment_slug: '',
      id: 'op-1',
      occurred_at: '2026-11-23T18:00:00Z',
      performed_by: AGENT_ID,
      project_slug: 'webform',
      recorded_by: AGENT_ID,
    } as OperationsLogRecord

    render(
      <OperationsLogStreamRow
        agentMap={new Map([[AGENT_ID, agent]])}
        entry={entry}
        id="op-1"
        isOpen={false}
        onToggle={() => {}}
        performerDisplayNames={new Map([[AGENT_ID, agent.name]])}
      />,
    )

    const avatar = screen.getByTitle('Dependency Bot')
    expect(avatar).toHaveTextContent('DB')
    // No Gravatar lookup for an agent id.
    expect(avatar.querySelector('img')).toBeNull()
  })
})
