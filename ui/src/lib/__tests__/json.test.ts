import { describe, expect, it, vi } from 'vitest'

import { parseJson } from '@/lib/json'
import { JSON_SOURCE } from '@/test/utils'

describe.skipIf(!JSON_SOURCE)('parseJson', () => {
  it.each([
    ['9007199254740993', '9007199254740993'],
    ['-12345678901234567890', '-12345678901234567890'],
    ['9007199254740993e0', '9007199254740993'],
    ['9007199254740993.0', '9007199254740993'],
    ['90071992547409.93e2', '9007199254740993'],
  ])('keeps %s as text', (token, text) => {
    const onKept = vi.fn()
    expect(parseJson(`[${token}]`, onKept)).toEqual([text])
    expect(onKept).toHaveBeenCalledTimes(1)
  })

  it.each(['9007199254740992', '1e22', '7', '1.5', '9007199254740993.5'])(
    'keeps %s as a number',
    (token) => {
      const onKept = vi.fn()
      expect(parseJson(`[${token}]`, onKept)).toEqual([Number(token)])
      expect(onKept).not.toHaveBeenCalled()
    },
  )
})
