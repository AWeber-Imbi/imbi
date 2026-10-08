import { describe, expect, it } from 'vitest'

import { capStatus, dailyValues, daysBetween } from '../agentUsage'
import { agent, usage } from './fixtures'

describe('capStatus', () => {
  const mender = agent() // monthly_cost_cap 400

  it('warns from 80% and is over from 100%', () => {
    expect(capStatus(mender, 319.99)).toBeNull()
    expect(capStatus(mender, 320)?.level).toBe('warning')
    expect(capStatus(mender, 400)?.level).toBe('over')
  })

  it('is null without a cap', () => {
    const noCap = agent({ settings: { monthly_cost_cap: null } })
    expect(capStatus(noCap, 1000)).toBeNull()
  })
})

describe('daysBetween', () => {
  it('includes both ends and crosses months', () => {
    expect(daysBetween('2026-09-29', '2026-10-02')).toEqual([
      '2026-09-29',
      '2026-09-30',
      '2026-10-01',
      '2026-10-02',
    ])
  })
})

describe('dailyValues', () => {
  it('fills days with no usage with zero', () => {
    const values = dailyValues(usage(), (row) => row.tasks)
    expect(values).toHaveLength(30)
    expect(values.slice(-3)).toEqual([0, 3, 2])
  })
})
