import { describe, expect, it, vi } from 'vitest'

import { downloadCsv } from '@/lib/csv'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { ScoreHistoryTab } from '../ScoreHistoryTab'

const POINTS = vi.hoisted(() => [
  {
    change_reason: 'policy_change',
    previous_score: 70,
    score: 75,
    timestamp: '2026-10-01T00:00:00Z',
  },
  {
    change_reason: 'ana@example.com',
    previous_score: 75,
    score: 80,
    timestamp: '2026-10-02T00:00:00Z',
  },
])

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getScoreHistory: vi.fn().mockResolvedValue({
    granularity: 'raw',
    points: POINTS,
    project_id: 'p-1',
  }),
  getScoreTrend: vi.fn().mockResolvedValue({ current: 80 }),
  listProjectEvents: vi.fn().mockResolvedValue({ entries: [] }),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/lib/csv', () => ({ downloadCsv: vi.fn() }))

describe('ScoreHistoryTab change events', () => {
  it('filters the events by reason and exports what is shown', async () => {
    render(<ScoreHistoryTab orgSlug="acme" projectId="p-1" />)
    expect(await screen.findByText('ana')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by reason' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Policy' }))

    await waitFor(() => expect(screen.queryByText('ana')).toBeNull())
    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(downloadCsv).toHaveBeenCalledWith(
      'score-history-p-1.csv',
      ['timestamp', 'reason', 'previous_score', 'score'],
      [['2026-10-01T00:00:00Z', 'policy_change', 70, 75]],
    )
  })
})
