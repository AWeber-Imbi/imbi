import { useState } from 'react'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { Environment } from '@/types'

import type { AgentTools } from '../agentDraft'
import { ToolsTab } from '../ToolsTab'
import { catalog } from './fixtures'

const auth = vi.hoisted(() => ({
  user: {
    is_admin: false,
    organizations: [
      { organization_slug: 'acme', permissions: ['agent:write'] },
    ],
    permissions: ['agent:write'] as string[],
  },
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

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
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['agent:write'] },
      ],
      permissions: ['agent:write'],
    }
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue(catalog())
    vi.mocked(endpoints.listEnvironments).mockResolvedValue([
      env('staging', 2),
      env('production', 1),
    ])
  })

  it('shows the Imbi tools open, with the counts', async () => {
    render(<Harness initial={{ 'imbi.get_me': {} as never }} />)
    expect(await screen.findAllByText('1 of 4 enabled')).toHaveLength(2)
    expect(
      screen.getByText(/come with the plugins in the Plugins section/),
    ).toBeInTheDocument()
    expect(within(group('Imbi')).getByText('imbi.list_projects')).toBeVisible()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(endpoints.getAgentToolCatalog).toHaveBeenCalledWith(
      'acme',
      false,
      expect.anything(),
    )
  })

  it('switches a tool on and sets approval and environments', async () => {
    render(<Harness initial={{}} />)
    await screen.findAllByText('0 of 4 enabled')
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
          'imbi.get_me': {
            approval: false,
            environments: null,
            rate_limit: null,
          },
        }}
      />,
    )
    await screen.findAllByText('1 of 4 enabled')
    fireEvent.click(screen.getByRole('button', { name: 'No limit' }))
    fireEvent.change(await screen.findByLabelText('Calls'), {
      target: { value: '6' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(last()['imbi.get_me'].rate_limit).toEqual({
      count: 6,
      per: 'hour',
    })
    expect(
      await screen.findByRole('button', { name: '6 / hr' }),
    ).toBeInTheDocument()
  })

  it('enables and disables every tool', async () => {
    render(<Harness initial={{}} />)
    await screen.findAllByText('0 of 4 enabled')
    fireEvent.click(screen.getByRole('button', { name: 'Enable all' }))
    expect(Object.keys(last()).sort()).toEqual([
      'imbi.create_project',
      'imbi.delete_project',
      'imbi.get_me',
      'imbi.list_projects',
    ])
    fireEvent.click(screen.getByRole('button', { name: 'Disable all' }))
    expect(last()).toEqual({})
  })

  it('switches a built-in tool on, without environments', async () => {
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue({
      ...catalog(),
      builtin_tools: [
        {
          capability: 'read',
          description: 'Load a skill.',
          key: 'builtin.Skill',
          name: 'Skill',
        },
      ],
    })
    render(<Harness initial={{}} />)
    await screen.findAllByText('0 of 1 enabled')
    expect(screen.getByText('0 of 5 enabled')).toBeInTheDocument()
    expect(within(group('Built-in')).getByText('builtin.Skill')).toBeVisible()
    fireEvent.click(
      screen.getByRole('switch', { name: 'Enable builtin.Skill' }),
    )
    expect(last()).toEqual({
      'builtin.Skill': {
        approval: false,
        environments: null,
        rate_limit: null,
      },
    })
    // Approval and a rate limit apply; an environment limit does not.
    expect(screen.getByRole('button', { name: 'Approval' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'No limit' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /: allowed$/ })).toBeNull()
  })

  it('lists an enabled tool that the catalog lacks, so it can be removed', async () => {
    render(<Harness initial={{ 'zoekt.search': {} as never }} />)
    await screen.findByText('Not in the catalog')
    fireEvent.click(screen.getByRole('button', { name: /Not in the catalog/ }))
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: 'Enable zoekt.search' }))
    expect(last()).toEqual({})
  })

  it('filters by search and enabled only', async () => {
    render(<Harness initial={{ 'imbi.get_me': {} as never }} />)
    await screen.findAllByText('1 of 4 enabled')
    fireEvent.change(screen.getByLabelText('Search tools'), {
      target: { value: 'nothing matches this' },
    })
    expect(screen.getByText('No tools match that search.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Search tools'), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enabled only' }))
    expect(screen.getByText('imbi.get_me')).toBeInTheDocument()
    expect(screen.queryByText('imbi.create_project')).toBeNull()
  })

  it('lists the tools again on refresh', async () => {
    render(<Harness initial={{}} />)
    await screen.findAllByText('0 of 4 enabled')
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh the tool list' }),
    )
    await waitFor(() =>
      expect(endpoints.getAgentToolCatalog).toHaveBeenCalledWith('acme', true),
    )
  })

  it('hides refresh without agent:write', async () => {
    auth.user = {
      is_admin: false,
      organizations: [
        { organization_slug: 'acme', permissions: ['agent:read'] },
      ],
      permissions: ['agent:read'],
    }
    render(<Harness initial={{}} />)
    await screen.findAllByText('0 of 4 enabled')
    expect(
      screen.queryByRole('button', { name: 'Refresh the tool list' }),
    ).toBeNull()
  })

  it.each([
    ['auth_failed', 'the API did not accept the credentials.'],
    ['timeout', 'the API did not answer in time.'],
    ['unreachable', 'the API is not reachable.'],
  ] as const)('shows a message for %s', async (code, message) => {
    vi.mocked(endpoints.getAgentToolCatalog).mockResolvedValue({
      ...catalog(),
      error: code,
      tools: [],
    })
    render(<Harness initial={{}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      `Could not list the tools: ${message}`,
    )
  })
})
