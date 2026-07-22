import { describe, expect, it } from 'vitest'

import { computeScoreYAxis } from '@/lib/score-chart'

describe('computeScoreYAxis', () => {
  it('keeps the 50–100 view when every score is at or above 50', () => {
    const { ticks, yMax, yMin } = computeScoreYAxis([53, 97, 100, 50])
    expect(yMin).toBe(50)
    expect(yMax).toBe(100)
    expect(ticks).toEqual([50, 60, 70, 80, 90, 100])
  })

  it('drops the floor in steps of 10 when a score falls below 50', () => {
    // Regression: a project that dipped to ~22 used to render below the chart
    // floor. The floor should now extend down far enough to contain it.
    const { ticks, yMax, yMin } = computeScoreYAxis([100, 22.09, 46.8, 53.2])
    expect(yMin).toBe(20)
    expect(yMax).toBe(100)
    expect(ticks).toEqual([20, 30, 40, 50, 60, 70, 80, 90, 100])
  })

  it('floors at 0 and never goes negative for very low scores', () => {
    const { ticks, yMin } = computeScoreYAxis([0, 3.5, 100])
    expect(yMin).toBe(0)
    expect(ticks[0]).toBe(0)
    expect(ticks[ticks.length - 1]).toBe(100)
  })

  it('defaults to the 50–100 view when there are no points', () => {
    const { ticks, yMax, yMin } = computeScoreYAxis([])
    expect(yMin).toBe(50)
    expect(yMax).toBe(100)
    expect(ticks).toEqual([50, 60, 70, 80, 90, 100])
  })
})
