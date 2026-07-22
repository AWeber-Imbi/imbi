import { MemoryRouter } from 'react-router-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SearchResult } from '@/api/endpoints'

import { SearchResultsPanel } from '../SearchResultsPanel'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'org' } }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))
// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useSearchEnrichment', () => ({
  useSearchEnrichment: () => new Map(),
}))

function makeResult(overrides: Partial<SearchResult>): SearchResult {
  return {
    attribute: 'description',
    chunk_text: 'a snippet',
    distance: 0.1,
    name: 'Untitled',
    node_id: 'n',
    node_label: 'Project',
    ...overrides,
  }
}

// A mixed result set: two Projects plus a Document and a Team that are both
// navigable (Document via project_id, Team via slug). Titles avoid the query
// string so highlightKeywords does not split them across spans.
const MIXED: SearchResult[] = [
  makeResult({ name: 'Alpha Project', node_id: 'p1', node_label: 'Project' }),
  makeResult({ name: 'Beta Project', node_id: 'p2', node_label: 'Project' }),
  makeResult({
    name: 'Gamma Doc',
    node_id: 'd1',
    node_label: 'Document',
    project_id: 'p1',
  }),
  makeResult({
    name: 'Delta Team',
    node_id: 't1',
    node_label: 'Team',
    slug: 'delta',
  }),
]

function renderPanel(results: SearchResult[]) {
  return render(
    <SearchResultsPanel
      isLoading={false}
      limit={20}
      onLimitChange={vi.fn()}
      onThresholdChange={vi.fn()}
      query="zzz"
      results={results}
      threshold={0.75}
    />,
    { wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter> },
  )
}

describe('SearchResultsPanel default filter', () => {
  it('defaults to Project results, hiding other types', () => {
    renderPanel(MIXED)
    expect(screen.getByText('Alpha Project')).toBeInTheDocument()
    expect(screen.getByText('Beta Project')).toBeInTheDocument()
    expect(screen.queryByText('Gamma Doc')).not.toBeInTheDocument()
    expect(screen.queryByText('Delta Team')).not.toBeInTheDocument()
  })

  it('reveals other types when the All pill is clicked', async () => {
    const user = userEvent.setup()
    renderPanel(MIXED)
    await user.click(screen.getByText('All 4'))
    expect(screen.getByText('Gamma Doc')).toBeInTheDocument()
    expect(screen.getByText('Delta Team')).toBeInTheDocument()
  })

  it('falls back to all results when the query returns no Projects', () => {
    renderPanel([
      makeResult({
        name: 'Gamma Doc',
        node_id: 'd1',
        node_label: 'Document',
        project_id: 'p1',
      }),
      makeResult({
        name: 'Delta Team',
        node_id: 't1',
        node_label: 'Team',
        slug: 'delta',
      }),
    ])
    // No Project results exist, so the Project default must not blank the
    // list — both non-project results stay visible.
    expect(screen.getByText('Gamma Doc')).toBeInTheDocument()
    expect(screen.getByText('Delta Team')).toBeInTheDocument()
  })
})
