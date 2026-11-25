import { describe, expect, it } from 'vitest'

import { overlapGroups } from '../subagentRuns'

describe('overlapGroups', () => {
  it('groups a run listed after one it does not overlap', () => {
    const a = [0, 5] as const
    const b = [6, 10] as const
    const c = [2, 12] as const
    expect(overlapGroups([a, b, c], (r) => r)).toEqual([[a, b, c]])
  })
})
