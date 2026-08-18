import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadCsv, toCsv } from '@/lib/csv'

describe('downloadCsv', () => {
  // jsdom implements neither object URLs nor a real anchor click, so
  // both are stubbed. What the assertions cover is everything this
  // helper actually decides: the filename, the bytes, and the anchor
  // lifecycle Firefox is strict about.
  function stubDownload() {
    const blobs: Blob[] = []
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: (blob: Blob) => {
        blobs.push(blob)
        return 'blob:test'
      },
      revokeObjectURL,
    })
    const clicked: { connected: boolean; download: string }[] = []
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push({
          connected: this.isConnected,
          download: this.download,
        })
      })
    return { blobs, click, clicked, revokeObjectURL }
  }

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('hands the browser a named file holding the rendered CSV', () => {
    const { blobs, click, clicked } = stubDownload()

    downloadCsv('report.csv', ['A'], [['1']])

    expect(click).toHaveBeenCalledOnce()
    expect(clicked[0].download).toBe('report.csv')
    expect(blobs[0].type).toBe('text/csv')
  })

  it('clicks the anchor while it is attached, then removes it', () => {
    const { clicked } = stubDownload()

    downloadCsv('report.csv', ['A'], [['1']])

    // Firefox ignores a synthetic click on a detached anchor.
    expect(clicked[0].connected).toBe(true)
    expect(document.querySelector('a[download]')).toBeNull()
  })

  it('defers revoking the object URL past the current tick', () => {
    vi.useFakeTimers()
    const { revokeObjectURL } = stubDownload()

    downloadCsv('report.csv', ['A'], [['1']])

    // Revoking in the same tick can abort a download just started.
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.runAllTimers()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test')
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
