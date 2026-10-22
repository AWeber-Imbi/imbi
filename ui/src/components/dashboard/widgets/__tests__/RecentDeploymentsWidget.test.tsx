import { describe, expect, it } from 'vitest'

import type { OperationsLogRecord } from '@/types'

import { deploymentStatus } from '../RecentDeploymentsWidget'

const row = (overrides: Partial<OperationsLogRecord>) =>
  ({
    completed_at: '2026-10-22T10:00:00Z',
    description: '{"action": "deploy"}',
    plugin_slug: 'github',
    ...overrides,
  }) as OperationsLogRecord

describe('deploymentStatus', () => {
  it('shows an open row as in progress', () => {
    expect(deploymentStatus(row({ completed_at: null })).label).toBe(
      'In Progress',
    )
  })

  it('shows a failed rollout as failed', () => {
    const d = row({ description: '{"action": "deploy", "status": "failed"}' })
    expect(deploymentStatus(d).label).toBe('Failed')
  })

  it('shows a rolled back rollout as rolled back', () => {
    const d = row({
      description: '{"action": "deploy", "status": "rolled_back"}',
    })
    expect(deploymentStatus(d).label).toBe('Rolled Back')
  })

  it('shows a closed row without a status as a success', () => {
    expect(deploymentStatus(row({})).label).toBe('Success')
  })
})
