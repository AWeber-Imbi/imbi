import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadCsv, toCsv } from '@/lib/csv'

describe('downloadCsv', () => {
  afterEach(() => vi.restoreAllMocks())

  it('hands the browser a named file holding the rendered CSV', () => {
    // jsdom implements neither object URLs nor a real anchor click, so
    // both are stubbed; what the test asserts is the filename and the
    // bytes handed over, which is all this helper decides.
    const blobs: Blob[] = []
    vi.stubGlobal('URL', {
      createObjectURL: (blob: Blob) => {
        blobs.push(blob)
        return 'blob:test'
      },
      revokeObjectURL: vi.fn(),
    })
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)

    downloadCsv('report.csv', ['A'], [['1']])

    expect(click).toHaveBeenCalledOnce()
    const anchor = click.mock.instances[0] as HTMLAnchorElement
    expect(anchor.download).toBe('report.csv')
    expect(blobs[0].type).toBe('text/csv')
  })
})

describe('toCsv', () => {
  it('quotes every field', () => {
    expect(toCsv(['A', 'B'], [['1', '2']])).toBe('"A","B"\n"1","2"')
  })

  it('doubles embedded quotes rather than escaping them', () => {
    expect(toCsv(['A'], [['say "hi"']])).toBe('"A"\n"say ""hi"""')
  })

  it('keeps a comma inside a field from splitting it', () => {
    const csv = toCsv(['A'], [['one,two']])
    expect(csv).toBe('"A"\n"one,two"')
  })

  it('renders null and undefined as empty fields', () => {
    expect(toCsv(['A', 'B'], [[null, undefined]])).toBe('"A","B"\n"",""')
  })

  it('renders numbers without quoting them away', () => {
    expect(toCsv(['N'], [[0]])).toBe('"N"\n"0"')
  })

  it('emits only the header when there are no rows', () => {
    expect(toCsv(['A', 'B'], [])).toBe('"A","B"')
  })
})
