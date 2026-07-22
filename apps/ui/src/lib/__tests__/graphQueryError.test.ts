import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { extractGraphQueryError } from '@/lib/graphQueryError'

describe('extractGraphQueryError', () => {
  it('unwraps the structured error from FastAPI detail envelopes', () => {
    const err = new ApiError(400, '', {
      detail: {
        error: {
          code: '42601',
          column: 14,
          message: 'syntax error at or near "RETUR"',
        },
      },
    })
    expect(extractGraphQueryError(err)).toEqual({
      code: '42601',
      column: 14,
      message: 'syntax error at or near "RETUR"',
    })
  })

  it('falls back to a plain string detail (e.g. 403)', () => {
    const err = new ApiError(403, '', { detail: 'Admin privileges required' })
    expect(extractGraphQueryError(err)).toEqual({
      message: 'Admin privileges required',
    })
  })

  it('still accepts an unwrapped error envelope', () => {
    const err = new ApiError(400, '', { error: { message: 'boom' } })
    expect(extractGraphQueryError(err)).toEqual({ message: 'boom' })
  })

  it('falls back to the HTTP status when no detail is present', () => {
    const err = new ApiError(400, '')
    expect(extractGraphQueryError(err).message).toBe('HTTP 400: ')
  })

  it('handles non-ApiError values', () => {
    expect(extractGraphQueryError(new Error('network down'))).toEqual({
      message: 'network down',
    })
    expect(extractGraphQueryError('weird')).toEqual({
      message: 'Unknown error',
    })
  })
})
