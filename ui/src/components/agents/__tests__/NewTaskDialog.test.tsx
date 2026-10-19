import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { Agent } from '@/types'

import { NewTaskDialog } from '../NewTaskDialog'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createAgentTask: vi.fn(),
  getProjects: vi.fn(),
  listAgents: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { is_admin: true, permissions: [] } }),
}))

const agent = {
  enabled: true,
  name: 'Fixer',
  organization: { slug: 'acme' },
  slug: 'fixer',
} as Agent

describe('NewTaskDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getProjects).mockResolvedValue([])
    vi.mocked(endpoints.listAgents).mockResolvedValue([agent])
    vi.mocked(endpoints.createAgentTask).mockResolvedValue({
      short_id: 'T-1',
    } as Awaited<ReturnType<typeof endpoints.createAgentTask>>)
  })

  it('needs an agent when none is fixed', async () => {
    render(<NewTaskDialog isOpen onClose={vi.fn()} />)
    expect(screen.getByText('New task')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Fix it' },
    })
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'Fix the bug' },
    })
    expect(
      await screen.findByRole('combobox', { name: 'Agent' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create task' })).toBeDisabled()
  })

  it('creates a task for a fixed agent, with no project', async () => {
    const onClose = vi.fn()
    render(<NewTaskDialog agent={agent} isOpen onClose={onClose} />)
    expect(screen.queryByRole('combobox', { name: 'Agent' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: ' Fix it ' },
    })
    fireEvent.change(screen.getByLabelText('Instruction'), {
      target: { value: 'Fix the bug' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(endpoints.createAgentTask).toHaveBeenCalledWith('acme', {
      agent_slug: 'fixer',
      description: 'Fix the bug',
      title: 'Fix it',
    })
  })
})
