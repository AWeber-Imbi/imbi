import { beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { OperationsLogRecord } from '@/types'

import { OperationsLogEntryDetails } from '../OperationsLogEntryDetails'

// fallow-ignore-next-line unresolved-import
vi.mock('@/components/NewOpsLogDialog', () => ({
  NewOpsLogDialog: () => null,
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  getOperationsLogEntry: vi.fn(async () => makeRecord()),
  listPluginOpsLogTemplates: vi.fn(async () => []),
}))

function makeRecord(
  overrides: Partial<OperationsLogRecord> = {},
): OperationsLogRecord {
  return {
    description: 'released v1.2.3 to testing',
    entry_type: 'Deployed',
    environment_slug: 'testing',
    id: 'opslog-1',
    occurred_at: '2026-05-12T02:24:59.841Z',
    project_id: 'proj-abc',
    project_slug: 'ai-content',
    recorded_at: '2026-05-12T02:24:59.841Z',
    recorded_by: 'alexs@aweber.com',
    version: 'v1.2.3',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('OperationsLogEntryDetails', () => {
  it('renders a Go to Project link pointing at the record project', () => {
    render(<OperationsLogEntryDetails entry={makeRecord()} />)
    const link = screen.getByRole('link', { name: /go to project/i })
    expect(link).toHaveAttribute('href', '/projects/proj-abc')
  })

  it('renders the Duplicate button alongside the project link', () => {
    render(<OperationsLogEntryDetails entry={makeRecord()} />)
    expect(
      screen.getByRole('button', { name: /duplicate/i }),
    ).toBeInTheDocument()
  })
})
