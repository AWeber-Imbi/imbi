import { describe, expect, it } from 'vitest'

import { fieldFilters, NO_FILTERS, readFilters } from '../taskFilters'

describe('fieldFilters', () => {
  it('sends a value with a comma as eq, and keeps it in the address', () => {
    const filters = {
      ...NO_FILTERS,
      fields: { area: ['a,b'], sev: ['1', '2'] },
    }
    const sent = fieldFilters(filters)
    expect(sent).toEqual(['area:eq:a,b', 'sev:in:1,2'])
    const search = sent.map((f) => `filter=${encodeURIComponent(f)}`)
    expect(readFilters(`?${search.join('&')}`).fields).toEqual(filters.fields)
  })

  it('leaves out a value with a comma among others', () => {
    const filters = { ...NO_FILTERS, fields: { area: ['a,b', 'c'] } }
    expect(fieldFilters(filters)).toEqual(['area:in:c'])
  })
})
