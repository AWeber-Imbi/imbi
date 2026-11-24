import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchConfigurationHistory,
  restoreConfigurationVersion,
} from '@/api/endpoints'
import { ConfigHistoryDialog } from '@/components/project/ConfigHistoryDialog'
import { render, screen, waitFor } from '@/test/utils'
import type { ConfigVersionResponse } from '@/types'

vi.mock('@/api/endpoints', () => ({
  fetchConfigurationHistory: vi.fn(),
  restoreConfigurationVersion: vi.fn(async () => ({})),
}))

const version = (
  v: string,
  value: null | string,
  secret = false,
): ConfigVersionResponse => ({
  data_type: secret ? 'secret' : 'string',
  last_modified: null,
  modified_by: 'jane',
  secret,
  value,
  version: v,
})

const renderDialog = () =>
  render(
    <ConfigHistoryDialog
      environment={{ name: 'Production', slug: 'production' }}
      onClose={() => {}}
      orgSlug="acme"
      paramKey="db/password"
      projectId="proj-1"
      source="aws"
    />,
  )

describe('ConfigHistoryDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('masks secret values until revealed', async () => {
    vi.mocked(fetchConfigurationHistory).mockResolvedValue([
      version('2', 'new-secret', true),
      version('1', 'old-secret', true),
    ])
    renderDialog()
    expect(await screen.findByText('v2')).toBeInTheDocument()
    expect(screen.queryByText('old-secret')).not.toBeInTheDocument()
    await userEvent.click(
      screen.getAllByRole('button', { name: 'Reveal value' })[1],
    )
    expect(screen.getByText('old-secret')).toBeInTheDocument()
  })

  it('shows hidden values when the API returns none', async () => {
    vi.mocked(fetchConfigurationHistory).mockResolvedValue([
      version('2', null, true),
      version('1', null, true),
    ])
    renderDialog()
    expect(await screen.findAllByText('Value hidden')).toHaveLength(2)
    expect(
      screen.queryByRole('button', { name: 'Reveal value' }),
    ).not.toBeInTheDocument()
  })

  it('restores an earlier version after confirmation', async () => {
    vi.mocked(fetchConfigurationHistory).mockResolvedValue([
      version('2', 'new'),
      version('1', 'old'),
    ])
    renderDialog()
    expect(await screen.findByText('Current')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /restore/i }))
    expect(restoreConfigurationVersion).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() =>
      expect(restoreConfigurationVersion).toHaveBeenCalledWith(
        'acme',
        'proj-1',
        'db/password',
        '1',
        { environment: 'production', source: 'aws' },
      ),
    )
  })
})
