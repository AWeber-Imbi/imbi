import { describe, expect, it } from 'vitest'

import type { DocumentReader } from '@/types'

import {
  bandCounts,
  bandFor,
  estimatedReadSeconds,
  formatDwell,
  formatReadTime,
} from './readershipHelpers'

function reader(overrides: Partial<DocumentReader> = {}): DocumentReader {
  return {
    engaged_seconds: 0,
    last_read_at: null,
    max_scroll_pct: 0,
    principal: 'someone@example.com',
    reads: 0,
    views: 1,
    ...overrides,
  }
}

const ESTIMATE = 360

describe('bandFor', () => {
  it('counts deep scrolling as engaged even on a short visit', () => {
    expect(bandFor(reader({ max_scroll_pct: 94 }), ESTIMATE)).toBe('engaged')
  })

  it('counts a full dwell as engaged even without scrolling', () => {
    expect(bandFor(reader({ engaged_seconds: ESTIMATE }), ESTIMATE)).toBe(
      'engaged',
    )
  })

  it('calls a half-way reader skimmed', () => {
    expect(bandFor(reader({ max_scroll_pct: 61 }), ESTIMATE)).toBe('skimmed')
    expect(bandFor(reader({ engaged_seconds: 180 }), ESTIMATE)).toBe('skimmed')
  })

  it('calls a shallow, short visit brief', () => {
    expect(
      bandFor(reader({ engaged_seconds: 24, max_scroll_pct: 18 }), ESTIMATE),
    ).toBe('brief')
  })

  it('ignores dwell when the document has no read estimate', () => {
    expect(bandFor(reader({ engaged_seconds: 9000 }), 0)).toBe('brief')
  })
})

describe('bandCounts', () => {
  it('tallies every reader into exactly one band', () => {
    const counts = bandCounts(
      [
        reader({ max_scroll_pct: 100, principal: 'a@example.com' }),
        reader({ max_scroll_pct: 94, principal: 'b@example.com' }),
        reader({ max_scroll_pct: 61, principal: 'c@example.com' }),
        reader({ max_scroll_pct: 18, principal: 'd@example.com' }),
      ],
      ESTIMATE,
    )
    expect(counts).toEqual({ brief: 1, engaged: 2, skimmed: 1 })
  })

  it('is all zeroes for no readers', () => {
    expect(bandCounts([], ESTIMATE)).toEqual({
      brief: 0,
      engaged: 0,
      skimmed: 0,
    })
  })
})

describe('formatDwell', () => {
  it('renders an em dash for no measured time', () => {
    expect(formatDwell(0)).toBe('—')
  })

  it('renders sub-minute times in seconds', () => {
    expect(formatDwell(41)).toBe('41s')
  })

  it('zero-pads the seconds of a minutes value', () => {
    expect(formatDwell(552)).toBe('9m 12s')
    expect(formatDwell(125)).toBe('2m 05s')
  })

  it('rolls over to hours', () => {
    expect(formatDwell(3900)).toBe('1h 5m')
  })
})

describe('formatReadTime', () => {
  it('rounds to whole minutes, never below one', () => {
    expect(formatReadTime(360)).toBe('6 min read')
    expect(formatReadTime(10)).toBe('1 min read')
  })

  it('is absent for an empty document', () => {
    expect(formatReadTime(0)).toBeNull()
  })
})

describe('estimatedReadSeconds', () => {
  it('matches the server estimate of 220 words per minute', () => {
    expect(estimatedReadSeconds('word '.repeat(220).trim())).toBe(60)
  })

  it('is zero for empty content', () => {
    expect(estimatedReadSeconds('   ')).toBe(0)
  })
})
