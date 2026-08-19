// The resolve call is the one place the blocker id and the optional
// resolution note cross the wire, so pin the request contract here.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { resolveReleaseBlocker } from './releases'

describe('resolveReleaseBlocker', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('URL-encodes the blocker id and sends a null note when omitted', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({})
    await resolveReleaseBlocker('acme', 'p1', 'v1.2.3', 'blk/1')
    expect(post).toHaveBeenCalledWith(
      '/organizations/acme/projects/p1/deployments/releases/v1.2.3/blockers/blk%2F1/resolve',
      { resolution_note: null },
    )
  })

  it('sends the resolution note when provided', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({})
    await resolveReleaseBlocker('acme', 'p1', 'v1.2.3', 'blk1', 'Fixed in CI')
    expect(post).toHaveBeenCalledWith(
      '/organizations/acme/projects/p1/deployments/releases/v1.2.3/blockers/blk1/resolve',
      { resolution_note: 'Fixed in CI' },
    )
  })
})
