import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, ApiError } from '../client'
import { createOrFindTag } from '../endpoints'

describe('createOrFindTag', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns the existing tag when the create conflicts', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(new ApiError(409, 'Conflict'))
    const existing = { name: 'Experiment', slug: 'experiment' }
    vi.spyOn(apiClient, 'get').mockResolvedValue([existing])
    await expect(
      createOrFindTag('acme', { name: 'Experiment' }),
    ).resolves.toEqual(existing)
  })

  it('returns the tag with the conflicting slug, not a name match', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(new ApiError(409, 'Conflict'))
    const conflict = { name: 'Archived', slug: 'experiment' }
    vi.spyOn(apiClient, 'get').mockResolvedValue([
      { name: 'Experiment', slug: 'legacy' },
      conflict,
    ])
    await expect(
      createOrFindTag('acme', { name: 'Experiment' }),
    ).resolves.toEqual(conflict)
  })

  it('throws other errors', async () => {
    const error = new ApiError(500, 'Server Error')
    vi.spyOn(apiClient, 'post').mockRejectedValue(error)
    await expect(createOrFindTag('acme', { name: 'X' })).rejects.toBe(error)
  })
})
