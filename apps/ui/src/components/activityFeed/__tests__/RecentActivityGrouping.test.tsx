import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { render, screen } from '@/test/utils'
import type { OperationsLogEntry } from '@/types'

import { RecentActivity } from '../../RecentActivity'

// Same actor + project, close in time -> one cluster. `iso` drives both the
// occurred_at and the grouping window.
function ops(
  iso: string,
  overrides: Partial<OperationsLogEntry> = {},
): OperationsLogEntry {
  return {
    change_type: 'Deployed',
    description: '',
    display_name: 'deployer[bot]',
    email_address: 'deployer@aweber.com',
    environment: 'production',
    id: Math.floor(Math.random() * 1e9),
    occurred_at: iso,
    project_id: 1,
    project_name: 'ai-content',
    recorded_at: iso,
    recorded_by: 'deployer',
    type: 'OperationsLogEntry',
    version: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(endpoints, 'listPluginOpsLogTemplates').mockResolvedValue([])
})

describe('RecentActivity grouping', () => {
  it('collapses a same-actor burst into one expandable group', async () => {
    render(
      <RecentActivity
        activities={[
          ops('2026-05-12T02:24:00.000Z'),
          ops('2026-05-12T02:20:00.000Z'),
          ops('2026-05-12T02:16:00.000Z'),
        ]}
      />,
    )
    // Group header: count badge + breakdown summary, collapsed by default.
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('3 deployed')).toBeInTheDocument()
    // Detail rows (environment label) are hidden until expanded.
    expect(screen.queryByText('production')).not.toBeInTheDocument()

    await userEvent.click(screen.getByText('3 deployed'))
    // Expanded: one detail row per underlying event.
    expect(screen.getAllByText('production')).toHaveLength(3)
  })

  it('does not group unrelated actors', () => {
    render(
      <RecentActivity
        activities={[
          ops('2026-05-12T02:24:00.000Z', {
            display_name: 'Alex S',
            email_address: 'alexs@aweber.com',
          }),
          ops('2026-05-12T02:20:00.000Z'),
        ]}
      />,
    )
    // Two single rows -> two sentences, no count badge.
    expect(screen.queryByText('2 deployed')).not.toBeInTheDocument()
    expect(screen.getByText('Alex S')).toBeInTheDocument()
  })

  it('auto-expands a failed (danger) group', () => {
    render(
      <RecentActivity
        activities={[
          ops('2026-05-12T02:24:00.000Z', { change_type: 'Rolled Back' }),
          ops('2026-05-12T02:20:00.000Z', { change_type: 'Rolled Back' }),
        ]}
      />,
    )
    // Danger clusters start expanded, so detail rows render without a click.
    expect(screen.getAllByText('production').length).toBeGreaterThan(0)
  })
})
