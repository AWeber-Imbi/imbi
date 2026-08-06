import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { DocumentAnalytics, DocumentReader } from '@/types'

import { DocumentReadershipPopover } from './DocumentReadershipPopover'

function analytics(
  overrides: Partial<DocumentAnalytics> = {},
): DocumentAnalytics {
  return {
    by_surface: [
      { surface: 'web', views: 71 },
      { surface: 'mcp', views: 4 },
    ],
    completion_rate: 0.63,
    estimated_read_seconds: 360,
    identities_visible: true,
    last_read_at: '2026-07-24T12:00:00Z',
    median_engaged_seconds: 125,
    p90_engaged_seconds: 468,
    readers: 16,
    reads: 45,
    trend: [
      { day: '2026-05-01', readers: 1, views: 2 },
      { day: '2026-05-02', readers: 3, views: 7 },
    ],
    views: 71,
    ...overrides,
  }
}

const READERS: DocumentReader[] = [
  {
    engaged_seconds: 552,
    last_read_at: '2026-07-08T12:00:00Z',
    max_scroll_pct: 100,
    principal: 'dave@example.com',
    reads: 2,
    views: 3,
  },
  {
    engaged_seconds: 24,
    last_read_at: '2026-05-31T12:00:00Z',
    max_scroll_pct: 18,
    principal: 'rob@example.com',
    reads: 0,
    views: 1,
  },
]

function renderPopover() {
  return render(<DocumentReadershipPopover documentId="doc-1" orgSlug="acme" />)
}

function stub(data: DocumentAnalytics, readers: DocumentReader[] = READERS) {
  vi.spyOn(endpoints, 'getDocumentAnalytics').mockResolvedValue(data)
  vi.spyOn(endpoints, 'listDocumentReaders').mockResolvedValue(readers)
}

afterEach(() => vi.restoreAllMocks())

describe('DocumentReadershipPopover', () => {
  it('renders nothing until the analytics land', () => {
    vi.spyOn(endpoints, 'getDocumentAnalytics').mockReturnValue(
      new Promise(() => {}),
    )
    const { container } = renderPopover()
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the unique reader count in the byline', async () => {
    stub(analytics())
    renderPopover()

    const trigger = await screen.findByRole('button', { name: /16\s*readers/ })
    expect(trigger).toBeInTheDocument()
  })

  it('singularizes a lone reader', async () => {
    stub(analytics({ readers: 1 }), [READERS[0]])
    renderPopover()

    expect(
      await screen.findByRole('button', { name: /1\s*reader$/ }),
    ).toBeInTheDocument()
  })

  it('opens onto views, with the agent fetches called out separately', async () => {
    stub(analytics())
    renderPopover()

    await userEvent.click(await screen.findByRole('button'))

    expect(screen.getByText('Readership')).toBeInTheDocument()
    expect(screen.getByText('views (all-time)')).toBeInTheDocument()
    expect(screen.getByText('71')).toBeInTheDocument()
    expect(screen.getByText(/Plus/)).toHaveTextContent(
      'Plus 4 agent fetches, not counted above.',
    )
    await waitFor(() => expect(screen.getByText('Engaged')).toBeInTheDocument())
    expect(screen.getByText('Brief')).toBeInTheDocument()
  })

  it('breaks readers into bands on the engagement tab', async () => {
    stub(analytics())
    renderPopover()

    await userEvent.click(await screen.findByRole('button'))
    await userEvent.click(screen.getByRole('radio', { name: 'Engagement' }))

    expect(screen.getByText('Depth')).toBeInTheDocument()
    expect(screen.getByText('9m 12s')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText(/Median 2m 05s/)).toHaveTextContent(
      'Median 2m 05s · p90 7m 48s · 63% completion',
    )
  })

  it('says so when the org does not expose reader identities', async () => {
    stub(analytics({ identities_visible: false }))
    renderPopover()

    await userEvent.click(await screen.findByRole('button'))

    expect(
      screen.getByText(
        'Individual readers are not shown for this organization.',
      ),
    ).toBeInTheDocument()
    expect(endpoints.listDocumentReaders).not.toHaveBeenCalled()
  })

  it('says so when nobody has been recorded yet', async () => {
    stub(analytics({ readers: 0, views: 0 }), [])
    renderPopover()

    await userEvent.click(await screen.findByRole('button'))

    await waitFor(() =>
      expect(
        screen.getByText('No individual reads recorded yet.'),
      ).toBeInTheDocument(),
    )
  })

  it('links out to the org-wide report', async () => {
    stub(analytics())
    renderPopover()

    await userEvent.click(await screen.findByRole('button'))

    expect(
      screen.getByRole('link', { name: 'View full readership report' }),
    ).toHaveAttribute('href', '/reports/document-readership')
  })
})
