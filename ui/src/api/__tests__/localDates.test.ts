import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../client'
import { getAgentUsage, getDashboardMetrics } from '../endpoints'

// The API buckets days in this zone, so the days are the user's days.
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone

describe('endpoints that count by day send the browser zone', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getDashboardMetrics', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({})
    await getDashboardMetrics()
    expect(get).toHaveBeenCalledWith(
      '/admin/dashboard/metrics',
      { tz },
      undefined,
    )
  })

  it('getAgentUsage', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({})
    await getAgentUsage('acme', { start: '2026-11-01' })
    expect(get).toHaveBeenCalledWith(
      '/organizations/acme/agent-usage/',
      { start: '2026-11-01', tz },
      undefined,
    )
  })
})
