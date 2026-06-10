import { describe, expect, it } from 'vitest'

import type { EventRecord } from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'

import { WebhookHistoryRow } from '../WebhookHistoryRow'

function makeEvent(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    attributed_to: '',
    id: 'evt-1',
    metadata: {},
    payload: {},
    project_id: 'proj-1',
    recorded_at: '2026-04-01T12:00:00Z',
    third_party_service: 'github-enterprise-cloud',
    type: 'pull_request',
    ...overrides,
  }
}

describe('WebhookHistoryRow disposition', () => {
  it('renders "Recorded · no handlers" when handlers is empty', () => {
    render(<WebhookHistoryRow event={makeEvent()} />)
    expect(screen.getByText(/Recorded.+no handlers/)).toBeInTheDocument()
  })

  it('renders "N handlers · ok" when every handler succeeded', () => {
    const event = makeEvent({
      metadata: {
        handlers: [
          { duration_ms: 12, handler: 'gh#open', status: 'succeeded' },
          { duration_ms: 8, handler: 'gh#notify', status: 'succeeded' },
        ],
      },
    })
    render(<WebhookHistoryRow event={event} />)
    expect(screen.getByText('2 handlers · ok')).toBeInTheDocument()
  })

  it('renders "N of M handlers ok" when any handler failed', () => {
    const event = makeEvent({
      metadata: {
        handlers: [
          { duration_ms: 12, handler: 'gh#open', status: 'succeeded' },
          { error: 'boom', handler: 'gh#notify', status: 'failed' },
        ],
      },
    })
    render(<WebhookHistoryRow event={event} />)
    expect(screen.getByText('1 of 2 handlers ok')).toBeInTheDocument()
  })

  it('expands to show handler list with status and duration', () => {
    const event = makeEvent({
      metadata: {
        handlers: [
          { duration_ms: 42, handler: 'gh#open', status: 'succeeded' },
        ],
      },
    })
    render(<WebhookHistoryRow event={event} />)
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByText('gh#open')).toBeInTheDocument()
    expect(screen.getByText('succeeded')).toBeInTheDocument()
    expect(screen.getByText('42ms')).toBeInTheDocument()
  })

  it('honors defaultOpen and shows the copy-link button', () => {
    render(<WebhookHistoryRow defaultOpen event={makeEvent()} />)
    expect(
      screen.getByRole('button', { name: /Copy event link/i }),
    ).toBeInTheDocument()
  })

  it('prefers metadata.event_type over the top-level type for the badge', () => {
    const event = makeEvent({
      metadata: { event_type: 'pull_request', handlers: [] },
      // After the type-category refactor the top-level `type` is
      // `'webhook'`; the per-source label lives in metadata.
      type: 'webhook',
    })
    render(<WebhookHistoryRow event={event} />)
    expect(screen.getByText('pull_request')).toBeInTheDocument()
    expect(screen.queryByText('webhook')).not.toBeInTheDocument()
  })

  it('falls back to top-level type when metadata.event_type is missing', () => {
    // Defensive against legacy rows recorded before the
    // category/subtype split.
    const event = makeEvent({ metadata: {}, type: 'legacy_event' })
    render(<WebhookHistoryRow event={event} />)
    expect(screen.getByText('legacy_event')).toBeInTheDocument()
  })

  it('links the project id to the project page in the detail panel', () => {
    render(
      <WebhookHistoryRow
        defaultOpen
        event={makeEvent({ project_id: 'proj-42' })}
        projectLabel="my-service"
      />,
    )
    const link = screen.getByRole('link', { name: /my-service/ })
    expect(link).toHaveAttribute('href', '/projects/proj-42')
  })
})
