import { describe, expect, it } from 'vitest'

import { clipsWithoutScroll } from './oxlint-plugin-overflow'

describe('clipsWithoutScroll', () => {
  it('flags a capped height with hidden overflow', () => {
    expect(clipsWithoutScroll('max-h-65 overflow-hidden px-6 py-4')).toBe(true)
  })

  it('flags arbitrary caps and the y-axis and clip variants', () => {
    expect(clipsWithoutScroll('max-h-[60vh] overflow-y-hidden')).toBe(true)
    expect(clipsWithoutScroll('max-h-96 overflow-clip')).toBe(true)
    expect(clipsWithoutScroll('max-h-[calc(100vh-48px)] overflow-hidden')).toBe(
      true,
    )
  })

  it('flags classes behind variants', () => {
    expect(clipsWithoutScroll('sm:max-h-40 md:overflow-hidden')).toBe(true)
    expect(
      clipsWithoutScroll('data-[state=open]:max-h-40 overflow-hidden'),
    ).toBe(true)
  })

  it('allows a capped height that scrolls', () => {
    expect(clipsWithoutScroll('max-h-65 overflow-y-auto px-6 py-4')).toBe(false)
    expect(clipsWithoutScroll('max-h-65 overflow-auto')).toBe(false)
    expect(clipsWithoutScroll('max-h-65 overflow-y-scroll')).toBe(false)
  })

  it('allows a scrolling axis next to a hidden one', () => {
    expect(
      clipsWithoutScroll('max-h-65 overflow-x-hidden overflow-y-auto'),
    ).toBe(false)
  })

  it('allows an intentional line clamp', () => {
    expect(clipsWithoutScroll('max-h-20 overflow-hidden line-clamp-3')).toBe(
      false,
    )
  })

  it('ignores hidden overflow without a height cap', () => {
    expect(clipsWithoutScroll('h-10 overflow-hidden rounded-lg')).toBe(false)
    expect(clipsWithoutScroll('overflow-hidden')).toBe(false)
  })

  it('ignores a height cap without hidden overflow', () => {
    expect(clipsWithoutScroll('max-h-[60vh] min-h-40 font-mono')).toBe(false)
  })

  it('does not treat overflow-x-hidden as clipping the height', () => {
    expect(clipsWithoutScroll('max-h-65 overflow-x-hidden')).toBe(false)
  })

  it('returns false for strings that are not classes', () => {
    expect(clipsWithoutScroll('')).toBe(false)
    expect(clipsWithoutScroll('just a sentence about max-h-')).toBe(false)
  })
})
