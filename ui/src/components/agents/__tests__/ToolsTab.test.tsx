import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { Environment } from '@/types'

import type { AgentTools } from '../agentDraft'
import { ToolsTab } from '../ToolsTab'
import { catalog } from './fixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getAgentToolCatalog: vi.fn(),
  listEnvironments: vi.fn(),
}))

const changes: AgentTools[] = []

function env(slug: string, sortOrder: number): Environment {
  return { name: slug, slug, sort_order: sortOrder } as Environment
}

function group(name: string): HTMLElement {
  const heading = screen.getByText(name, { selector: 'span' })
  return heading.closest('.rounded-lg') as HTMLElement
}

function Harness({ initial }: { initial: AgentTools }) {
  const [tools, setTools] = useState(initial)
  return (
    <ToolsTab
      onChange={(next) => {
        changes.push(next)
        setTools(next)
      }}
      orgSlug="acme"
      value={tools}
    />
  )
}

function last(): AgentTools {
  return changes[changes.length - 1]
}

describe('ToolsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    changes.length = 0
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue(catalog())
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([
      env('staging', 2),
      env('production', 1),
    ])
  })

  it('shows the groups, the counts, and a server error', async () => {
    render(<Harness initial={{ 'github.read_file': {} as never }} />)
    expect(await screen.findByText('1 of 4 enabled')).toBeInTheDocument()
    expect(screen.getByText(/Imbi does not run agents yet/)).toBeInTheDocument()
    expect(
      within(group('GitHub')).getByText('1 of 2 enabled'),
    ).toBeInTheDocument()
    expect(within(group('Sentry')).getByRole('alert')).toHaveTextContent(
      'Could not list the tools of this server: Timed out after 10s',
    )
    expect(endpoints.getAgentToolCatalog).toHaveBeenCalledWith(
      'acme',
      false,
      expect.anything(),
    )
  })

  it('switches a tool on and sets approval and environments', async () => {
    render(<Harness initial={{}} />)
    await screen.findByText('0 of 4 enabled')
    fireEvent.click(screen.getByRole('button', { name: /Imbi/ }))
    fireEvent.click(
      screen.getByRole('switch', { name: 'Enable imbi.list_projects' }),
    )
    expect(last()).toEqual({
      'imbi.list_projects': {
        approval: false,
        environments: null,
        rate_limit: null,
      },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Approval' }))
    expect(last()['imbi.list_projects'].approval).toBe(true)

    // Environment chips follow the sort order of the org.
    await screen.findByRole('button', { name: 'production: allowed' })
    const chips = screen.getAllByRole('button', { name: /: allowed$/ })
    expect(chips.map((c) => c.textContent)).toEqual(['production', 'staging'])
    fireEvent.click(chips[0])
    expect(last()['imbi.list_projects'].environments).toEqual(['staging'])
  })

  it('sets a rate limit', async () => {
    render(
      <Harness
        initial={{
          'github.read_file': {
            approval: false,
            environments: null,
            rate_limit: null,
          },
        }}
      />,
    )
    await screen.findByText('1 of 4 enabled')
    fireEvent.click(screen.getByRole('button', { name: /GitHub/ }))
    fireEvent.click(screen.getByRole('button', { name: 'No limit' }))
    fireEvent.change(await screen.findByLabelText('Calls'), {
      target: { value: '6' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(last()['github.read_file'].rate_limit).toEqual({
      count: 6,
      per: 'hour',
    })
    expect(
      await screen.findByRole('button', { name: '6 / hr' }),
    ).toBeInTheDocument()
  })

  it('enables and disables a whole server', async () => {
    render(<Harness initial={{}} />)
    await screen.findByText('0 of 4 enabled')
    fireEvent.click(
      within(group('GitHub')).getByRole('button', { name: 'Enable all' }),
    )
    expect(Object.keys(last()).sort()).toEqual([
      'github.create_pull_request',
      'github.read_file',
    ])
    fireEvent.click(
      within(group('GitHub')).getByRole('button', { name: 'Disable all' }),
    )
    expect(last()).toEqual({})
  })

  it('lists an enabled tool that the catalog lacks, so it can be removed', async () => {
    render(<Harness initial={{ 'gone.old_tool': {} as never }} />)
    await screen.findByText('Not in the catalog')
    fireEvent.click(screen.getByRole('button', { name: /Not in the catalog/ }))
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('switch', { name: 'Enable gone.old_tool' }),
    )
    expect(last()).toEqual({})
  })

  it('filters by search and enabled only', async () => {
    render(<Harness initial={{ 'github.read_file': {} as never }} />)
    await screen.findByText('1 of 4 enabled')
    fireEvent.change(screen.getByLabelText('Search tools'), {
      target: { value: 'nothing matches this' },
    })
    // The failed server stays, so its error stays visible.
    expect(screen.queryByText('GitHub')).not.toBeInTheDocument()
    expect(screen.getByText('Sentry')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search tools'), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enabled only' }))
    expect(screen.getByText('github.read_file')).toBeInTheDocument()
    expect(screen.queryByText('github.create_pull_request')).toBeNull()
    expect(screen.queryByText('Imbi')).not.toBeInTheDocument()
  })

  it('lists the tools again on refresh', async () => {
    render(<Harness initial={{}} />)
    await screen.findByText('0 of 4 enabled')
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh the tool list' }),
    )
    await waitFor(() =>
      expect(endpoints.getAgentToolCatalog).toHaveBeenCalledWith('acme', true),
    )
  })
})
