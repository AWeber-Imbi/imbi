import { vi } from 'vitest'

import { fireEvent } from '@/test/utils'

interface Layout {
  /** The full height of what the pane scrolls. */
  content: (pane: HTMLElement) => number
  isPane: (el: HTMLElement) => boolean
  pane: number
  row: ((row: HTMLElement) => number) | number
}

/**
 * Records the text of each node the search highlight marks, since jsdom
 * has no CSS.highlights.
 */
export function captureHighlights() {
  const marked: { current: string[] } = { current: [] }
  const observers: MutationCallback[] = []
  vi.stubGlobal('CSS', {
    highlights: {
      delete: () => {
        marked.current = []
      },
      set: (_: string, highlight: { ranges: Range[] }) => {
        marked.current = highlight.ranges.map(
          (r) => r.startContainer.textContent ?? '',
        )
      },
    },
  })
  vi.stubGlobal(
    'Highlight',
    class {
      ranges: Range[]
      constructor(...ranges: Range[]) {
        this.ranges = ranges
      }
    },
  )
  vi.stubGlobal(
    'MutationObserver',
    class {
      constructor(callback: MutationCallback) {
        observers.push(callback)
      }
      disconnect() {}
      observe() {}
      takeRecords() {
        return []
      }
    },
  )
  const mutate = () => {
    for (const callback of observers)
      callback([], {} as unknown as MutationObserver)
  }
  return { marked, mutate }
}

/**
 * Gives a scroll pane and its virtual rows a height and a scroll
 * position, as a browser would, so the virtualizer renders a window
 * instead of every row.
 */
export function layout({ content, isPane, pane, row }: Layout) {
  const tops = new WeakMap<Element, number>()
  const max = (el: HTMLElement) => Math.max(0, content(el) - pane)
  const spies = [
    vi
      .spyOn(HTMLElement.prototype, 'offsetHeight', 'get')
      .mockImplementation(function (this: HTMLElement) {
        if (this.dataset.index !== undefined)
          return typeof row === 'number' ? row : row(this)
        return isPane(this) ? pane : 0
      }),
    vi
      .spyOn(Element.prototype, 'clientHeight', 'get')
      .mockImplementation(function (this: Element) {
        return this instanceof HTMLElement && isPane(this) ? pane : 0
      }),
    vi
      .spyOn(Element.prototype, 'scrollHeight', 'get')
      .mockImplementation(function (this: Element) {
        return this instanceof HTMLElement && isPane(this) ? content(this) : 0
      }),
    vi
      .spyOn(Element.prototype, 'scrollTop', 'get')
      .mockImplementation(function (this: Element) {
        return tops.get(this) ?? 0
      }),
    vi
      .spyOn(Element.prototype, 'scrollTop', 'set')
      .mockImplementation(function (this: Element, top: number) {
        const limit =
          this instanceof HTMLElement && isPane(this) ? max(this) : 0
        const next = Math.max(0, Math.min(top, limit))
        if (next === (tops.get(this) ?? 0)) return
        tops.set(this, next)
        queueMicrotask(() => fireEvent.scroll(this))
      }),
  ]
  const scrollTo = Element.prototype.scrollTo
  Element.prototype.scrollTo = function (
    this: Element,
    options?: number | ScrollToOptions,
  ) {
    if (typeof options === 'object' && options.top !== undefined)
      this.scrollTop = options.top
  }
  return {
    mockRestore: () => {
      for (const spy of spies) spy.mockRestore()
      Element.prototype.scrollTo = scrollTo
    },
  }
}

/** Scrolls a pane to `top` and tells it, as the browser would. */
export function scrollPane(pane: HTMLElement, top: number) {
  pane.scrollTop = top
  fireEvent.scroll(pane)
}

/** The content height of a pane holding a table of `row`-high rows. */
export function tableHeight(row: number) {
  return (pane: HTMLElement) =>
    Number(pane.querySelector('table')?.getAttribute('aria-rowcount') ?? 0) *
    row
}
