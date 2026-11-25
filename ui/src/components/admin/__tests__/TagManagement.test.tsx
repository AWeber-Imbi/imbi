import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor, within } from '@/test/utils'
import type { Tag } from '@/types'

import { TagManagement } from '../TagManagement'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteTag: vi.fn(),
  listTags: vi.fn(),
  mergeTag: vi.fn(),
  patchTag: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => true,
}))

function tag(slug: string, documents: number, agents: number): Tag {
  return {
    color: '#5A89C9',
    id: `id-${slug}`,
    name: slug.charAt(0).toUpperCase() + slug.slice(1),
    organization: { name: 'Acme', slug: 'acme' },
    relationships: {
      agents: { count: agents, href: '' },
      documents: { count: documents, href: '' },
    },
    slug,
  }
}

describe('TagManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listTags).mockResolvedValue([
      tag('experiment', 2, 4),
      tag('runbook', 7, 0),
    ])
  })

  it('lists tags with their usage counts', async () => {
    render(<TagManagement />)
    const row = (await screen.findByText('Experiment')).closest('tr')!
    expect(within(row).getByText('experiment')).toBeInTheDocument()
    expect(within(row).getByText('2')).toBeInTheDocument()
    expect(within(row).getByText('4')).toBeInTheDocument()
    expect(screen.getByText('Runbook')).toBeInTheDocument()
  })

  it('merges a tag into another tag', async () => {
    vi.mocked(endpoints.mergeTag).mockResolvedValue(tag('runbook', 9, 4))
    render(<TagManagement />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Merge Experiment' }),
    )
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Merge into' }), {
      key: 'ArrowDown',
    })
    fireEvent.click(
      await screen.findByRole('option', { name: 'Runbook (runbook)' }),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Merge into "Runbook"' }),
    )
    await waitFor(() =>
      expect(endpoints.mergeTag).toHaveBeenCalledWith(
        'acme',
        'experiment',
        'runbook',
      ),
    )
    await waitFor(() => expect(endpoints.listTags).toHaveBeenCalledTimes(2))
  })

  it('patches only the changed fields', async () => {
    vi.mocked(endpoints.patchTag).mockResolvedValue(tag('runbook', 7, 0))
    render(<TagManagement />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Runbook' }))
    fireEvent.click(screen.getByRole('radio', { name: 'No color' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(endpoints.patchTag).toHaveBeenCalledWith('acme', 'runbook', [
        { op: 'replace', path: '/color', value: null },
      ]),
    )
  })
})
