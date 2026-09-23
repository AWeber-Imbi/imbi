import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getDashboardIggy } from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { IggyTopic } from '@/types'

import { IggyTopicsCard } from '../IggyTopicsCard'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getDashboardIggy: vi.fn(),
}))

function topic(overrides: Partial<IggyTopic>): IggyTopic {
  return {
    consumer_group: 'commits',
    current_offset: 45874,
    lag: null,
    members: 1,
    members_owning: 1,
    messages: 45875,
    size_bytes: 1024,
    stored_offset: null,
    stream: 'commits',
    topic: 'github',
    ...overrides,
  }
}

describe('IggyTopicsCard', () => {
  beforeEach(() => {
    vi.mocked(getDashboardIggy).mockReset()
  })

  it('summarizes the topics and shows no offset until Iggy has one', async () => {
    vi.mocked(getDashboardIggy).mockResolvedValue({
      checked_at: '2026-09-23T20:00:00Z',
      topics: [
        topic({}),
        topic({ current_offset: 0, messages: 0, topic: 'maintenance' }),
      ],
    })
    render(<IggyTopicsCard />)
    expect(
      await screen.findByText('1 streams · 2 topics · 45,875 messages'),
    ).toBeInTheDocument()
    expect(screen.getByText('All topics owned')).toBeInTheDocument()
    expect(screen.getByText('45,874')).toBeInTheDocument()
    // Stored and Lag for each of the two rows.
    expect(screen.getAllByText('—')).toHaveLength(4)
  })

  it('flags a group with a member that owns no partition', async () => {
    vi.mocked(getDashboardIggy).mockResolvedValue({
      checked_at: '2026-09-23T20:00:00Z',
      topics: [
        topic({
          consumer_group: 'operations_log',
          members: 2,
          stream: 'operations_log',
          topic: 'deployments',
        }),
      ],
    })
    render(<IggyTopicsCard />)
    expect(await screen.findByText('1 unowned')).toBeInTheDocument()
  })
})
