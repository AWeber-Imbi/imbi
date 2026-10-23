import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen } from '@/test/utils'
import type { EgressDestination } from '@/types'

import { emptyDraft } from '../agentDraft'
import { SettingsTab } from '../SettingsTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({ listEgressDestinations: vi.fn() }))

describe('SettingsTab egress destinations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.listEgressDestinations).mockResolvedValue([
      { name: 'Main Postgres', slug: 'pg-main' } as EgressDestination,
    ])
  })

  it('selects the destinations of the organization', async () => {
    const onChange = vi.fn()
    render(
      <SettingsTab
        errors={{}}
        onChange={onChange}
        orgSlug="acme"
        value={emptyDraft().settings}
      />,
    )
    fireEvent.click(await screen.findByRole('checkbox'))
    expect(endpoints.listEgressDestinations).toHaveBeenCalledWith(
      'acme',
      expect.anything(),
    )
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ egressDestinations: ['pg-main'] }),
    )
  })

  it('keeps a selected destination that is not available', async () => {
    const onChange = vi.fn()
    render(
      <SettingsTab
        errors={{}}
        onChange={onChange}
        orgSlug="acme"
        value={{ ...emptyDraft().settings, egressDestinations: ['gone'] }}
      />,
    )
    await screen.findByText('Main Postgres')
    expect(screen.getByText('Not available')).toBeInTheDocument()
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes[1]).toBeChecked()
    fireEvent.click(boxes[1])
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ egressDestinations: [] }),
    )
  })
})
