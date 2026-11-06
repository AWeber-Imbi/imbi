import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { extractApiErrorDetail } from '@/lib/apiError'

describe('extractApiErrorDetail', () => {
  it('prefers detail.message over the detail.error code', () => {
    const err = new ApiError(422, 'Unprocessable Entity', {
      detail: {
        error: 'invalid_configuration',
        message: 'role_arn is required',
      },
    })
    expect(extractApiErrorDetail(err)).toBe('role_arn is required')
  })

  it('falls back to detail.error when there is no message', () => {
    const err = new ApiError(401, 'Unauthorized', {
      detail: { error: 'identity_required', start_url: '/x' },
    })
    expect(extractApiErrorDetail(err)).toBe('identity_required')
  })
})
