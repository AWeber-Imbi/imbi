import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen, waitFor } from '@/test/utils'
import type { DocumentTemplate } from '@/types'

import { NewDocumentMenu } from './NewDocumentMenu'

vi.mock('@/api/endpoints', async () => {
  const actual = await vi.importActual<typeof endpoints>('@/api/endpoints')
  return { ...actual, listDocumentTemplates: vi.fn() }
})

function template(overrides: Partial<DocumentTemplate> = {}): DocumentTemplate {
  return {
    content: '# ADR',
    description: 'An Architectural Decision',
    icon: null,
    id: 'tpl-1',
    name: 'Architecture Decision Record',
    project_type_slugs: [],
    slug: 'adr',
    sort_order: 1,
    // No tags: the chip renders a LabelChip, which needs a
    // ThemeProvider that `@/test/utils` does not wrap. Tags are not
    // what this test is about.
    tags: [],
    title: null,
    type: 'project',
    ...overrides,
  }
}

describe('NewDocumentMenu', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  // Every seeded template is type 'project'. Excluding those on the org
  // page emptied the menu, and the control silently degraded to a plain
  // button with no way to start from a template.
  it('offers project templates on the org page', async () => {
    vi.mocked(endpoints.listDocumentTemplates).mockResolvedValue([template()])
    render(<NewDocumentMenu context="org" onCreate={vi.fn()} orgSlug="acme" />)
    // The trigger looks the same while the query is in flight, so opening
    // it proves nothing until the templates have landed. Assert on the
    // menu item itself -- that is the template the org context used to
    // filter away.
    await userEvent.click(
      await screen.findByRole('button', { name: /new document/i }),
    )
    expect(
      await screen.findByRole('menuitem', {
        name: /Architecture Decision Record/,
      }),
    ).toBeInTheDocument()
  })

  it('degrades to a plain button when there are no templates', async () => {
    vi.mocked(endpoints.listDocumentTemplates).mockResolvedValue([])
    render(<NewDocumentMenu context="org" onCreate={vi.fn()} orgSlug="acme" />)
    // The plain-button fallback only applies once the query settles, so
    // wait the loading state out rather than sampling the first render.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /new document/i }),
      ).not.toHaveAttribute('aria-haspopup'),
    )
  })
})
