import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import type { Project, ProjectRelationship } from '@/types'

import { EditRelationshipsDialog } from '../EditRelationshipsDialog'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    addProjectRelationship: vi.fn(),
    getProjects: vi.fn(),
    removeProjectRelationship: vi.fn(),
  }
})

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

const PROJECTS = [
  { archived: false, id: 'p1', name: 'Current', slug: 'current' },
  { archived: false, id: 'p3', name: 'Active', slug: 'active' },
  { archived: true, id: 'p2', name: 'Legacy', slug: 'legacy' },
] as Project[]

// The project list endpoint hides archived projects by default.
const LISTED_PROJECTS = PROJECTS.filter((p) => !p.archived)

const RELATIONSHIPS = [
  {
    direction: 'outbound',
    project: { id: 'p2', name: 'Legacy', slug: 'legacy' },
    type: 'depends_on',
  },
] as ProjectRelationship[]

function renderDialog(onClose = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <EditRelationshipsDialog
        isOpen
        onClose={onClose}
        projectId="p1"
        projectName="Current"
        relationships={RELATIONSHIPS}
      />
    </QueryClientProvider>,
  )
}

describe('EditRelationshipsDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getProjects).mockResolvedValue(LISTED_PROJECTS)
    vi.mocked(endpoints.removeProjectRelationship).mockResolvedValue(
      undefined,
    )
    vi.mocked(endpoints.addProjectRelationship).mockResolvedValue(undefined)
  })

  it('lets an archived dependency be removed', async () => {
    const onClose = vi.fn()
    renderDialog(onClose)

    const row = (await screen.findByText('Legacy')).closest('label')
    expect(row).not.toBeNull()
    fireEvent.click(within(row!).getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Save 1 change' }))

    await vi.waitFor(() => {
      expect(endpoints.removeProjectRelationship).toHaveBeenCalledWith(
        'acme',
        'p1',
        'p2',
      )
    })
    expect(endpoints.addProjectRelationship).not.toHaveBeenCalled()
  })
})
