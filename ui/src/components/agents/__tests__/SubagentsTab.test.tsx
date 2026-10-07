import { useState } from 'react'

import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'
import type { AgentSubagent } from '@/types'

import { SubagentsTab } from '../SubagentsTab'
import { agent } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ listAgents: vi.fn() }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

const changes: AgentSubagent[][] = []
let queryClient: QueryClient

function Harness({
  initial,
  saved,
}: {
  initial: AgentSubagent[]
  saved?: AgentSubagent[]
}) {
  const [value, setValue] = useState(initial)
  queryClient = useQueryClient()
  return (
    <SubagentsTab
      agentId="agt-1"
      onChange={(next) => {
        changes.push(next)
        setValue(next)
      }}
      orgSlug="acme"
      saved={saved}
      value={value}
    />
  )
}

function last(): AgentSubagent[] {
  return changes[changes.length - 1]
}

describe('SubagentsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    changes.length = 0
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent(),
      agent({ description: 'Posts summaries.', id: 'agt-2', name: 'Herald' }),
      agent({ id: 'agt-3', name: 'Scribe' }),
      agent({ enabled: false, id: 'agt-4', name: 'Warden' }),
      agent({ enabled: false, id: 'agt-5', name: 'Auditor' }),
    ])
  })

  it('lists the other enabled agents and the selected disabled ones', async () => {
    render(<Harness initial={[{ agent_id: 'agt-4', instructions: '' }]} />)
    expect(await screen.findByText('1 of 3 agents')).toBeInTheDocument()
    expect(screen.getByText('Herald')).toBeInTheDocument()
    expect(screen.getByText('Posts summaries.')).toBeInTheDocument()
    expect(screen.getByText('Warden')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    // Not the agent itself, and not a disabled agent that is not selected.
    expect(screen.queryByText('Mender')).not.toBeInTheDocument()
    expect(screen.queryByText('Auditor')).not.toBeInTheDocument()
    expect(screen.getByText(/Delegation depth is capped at 2/)).toBeVisible()
    expect(screen.getByText(/Imbi does not run agents yet/)).toBeVisible()
    expect(
      screen.queryByRole('textbox', { name: 'Search agents' }),
    ).not.toBeInTheDocument()
  })

  it('does not count a selected agent that is not in the list', async () => {
    render(
      <Harness
        initial={[
          { agent_id: 'agt-2', instructions: '' },
          { agent_id: 'agt-gone', instructions: '' },
        ]}
      />,
    )
    expect(await screen.findByText('1 of 2 agents')).toBeInTheDocument()
  })

  it('keeps a saved disabled agent after you clear it', async () => {
    const initial = [{ agent_id: 'agt-4', instructions: '' }]
    render(<Harness initial={initial} saved={initial} />)
    const warden = await screen.findByRole('checkbox', {
      name: 'Delegate to Warden',
    })
    fireEvent.click(warden)
    expect(last()).toEqual([])
    expect(screen.getByText('0 of 3 agents')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Delegate to Warden' }),
    )
    expect(last()).toEqual(initial)
  })

  it('adds subagents in order and sets instructions', async () => {
    render(<Harness initial={[]} />)
    fireEvent.click(
      await screen.findByRole('checkbox', { name: 'Delegate to Scribe' }),
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Delegate to Herald' }),
    )
    expect(last()).toEqual([
      { agent_id: 'agt-3', instructions: '' },
      { agent_id: 'agt-2', instructions: '' },
    ])
    expect(screen.getByText('2 of 2 agents')).toBeInTheDocument()

    const [first] = screen.getAllByRole('button', { name: /Add instructions/ })
    fireEvent.click(first)
    const field = screen.getByLabelText('Delegation instructions for Herald')
    fireEvent.change(field, { target: { value: 'Only post summaries.' } })
    expect(last()).toEqual([
      { agent_id: 'agt-3', instructions: '' },
      { agent_id: 'agt-2', instructions: 'Only post summaries.' },
    ])
    expect(
      screen.getByText(/Appended to Herald's own system prompt/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Instructions set/ }),
    ).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Delegate to Scribe' }),
    )
    expect(last()).toEqual([
      { agent_id: 'agt-2', instructions: 'Only post summaries.' },
    ])
  })

  it('shows a search field when there are more than 10 agents', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue(
      Array.from({ length: 12 }, (_, i) =>
        agent({ id: `agt-${i + 2}`, name: `Agent ${i + 2}` }),
      ),
    )
    render(<Harness initial={[]} />)
    const search = await screen.findByRole('textbox', {
      name: 'Search agents',
    })
    fireEvent.change(search, { target: { value: 'agent 13' } })
    expect(screen.getByText('Agent 13')).toBeInTheDocument()
    expect(screen.queryByText('Agent 12')).not.toBeInTheDocument()
    fireEvent.change(search, { target: { value: 'nothing' } })
    expect(screen.getByText('No agents match that search.')).toBeVisible()
  })

  it('keeps an active search field when the list gets shorter', async () => {
    vi.mocked(endpoints.listAgents).mockResolvedValue(
      Array.from({ length: 12 }, (_, i) =>
        agent({ id: `agt-${i + 2}`, name: `Agent ${i + 2}` }),
      ),
    )
    render(<Harness initial={[]} />)
    const search = await screen.findByRole('textbox', {
      name: 'Search agents',
    })
    fireEvent.change(search, { target: { value: 'nothing' } })
    vi.mocked(endpoints.listAgents).mockResolvedValue([
      agent({ id: 'agt-2', name: 'Herald' }),
    ])
    await queryClient.refetchQueries()
    expect(await screen.findByText('0 of 1 agents')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search agents' }), {
      target: { value: '' },
    })
    expect(screen.getByText('Herald')).toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: 'Search agents' }),
    ).not.toBeInTheDocument()
  })
})
