import { Route, Routes } from 'react-router-dom'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as endpoints from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { EgressDestination } from '@/types'

import { parsePorts } from '../egress-destinations/ports'
import { EgressDestinationManagement } from '../EgressDestinationManagement'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  createEgressDestination: vi.fn(),
  deleteEgressDestination: vi.fn(),
  getEgressSyncStatus: vi.fn(),
  listEgressDestinationChanges: vi.fn(),
  listEgressDestinations: vi.fn(),
  updateEgressDestination: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({
    organizations: [{ name: 'Acme', slug: 'acme' }],
    selectedOrganization: { slug: 'acme' },
  }),
}))

const NOW = new Date().toISOString()

function destination(
  overrides: Partial<EgressDestination> = {},
): EgressDestination {
  return {
    agents: [],
    applied_generation: 2,
    cidrs: ['10.20.0.0/16'],
    created_at: NOW,
    description: null,
    generation: 2,
    global: false,
    name: 'Main Postgres',
    organizations: ['acme'],
    pending: false,
    ports: [{ port: 5432, protocol: 'TCP' }],
    slug: 'pg-main',
    updated_at: NOW,
    ...overrides,
  }
}

const mountAt = (path: string) => {
  window.history.pushState({}, '', path)
  render(
    <Routes>
      <Route
        element={<EgressDestinationManagement />}
        path="/admin/:section?/:slug?/:action?"
      />
    </Routes>,
  )
}

describe('EgressDestinationManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(endpoints.getEgressSyncStatus).mockResolvedValue({
      synced_at: NOW,
      synced_by: 'pool-general',
    })
    vi.mocked(endpoints.listEgressDestinationChanges).mockResolvedValue([])
  })

  it('lists destinations with the pending state', async () => {
    vi.mocked(endpoints.listEgressDestinations).mockResolvedValue([
      destination(),
      destination({
        applied_generation: 1,
        generation: 2,
        global: true,
        name: 'DNS',
        pending: true,
        ports: [{ port: 53, protocol: 'UDP' }],
        slug: 'dns',
      }),
    ])
    mountAt('/admin/egress-destinations')
    expect(await screen.findByText('Main Postgres')).toBeInTheDocument()
    expect(endpoints.listEgressDestinations).toHaveBeenCalledWith(
      undefined,
      expect.anything(),
    )
    expect(screen.getByText('pending')).toHaveAttribute('title', 'Applied: g1')
    expect(screen.getAllByText('pending')).toHaveLength(1)
    expect(screen.getByText('53/UDP')).toBeInTheDocument()
    expect(screen.getByText('global')).toBeInTheDocument()
    expect(await screen.findByText(/Last sync:/)).not.toHaveTextContent('never')
  })

  it('creates a destination', async () => {
    vi.mocked(endpoints.listEgressDestinations).mockResolvedValue([])
    vi.mocked(endpoints.createEgressDestination).mockResolvedValue(
      destination(),
    )
    mountAt('/admin/egress-destinations/new')
    fireEvent.change(await screen.findByLabelText(/^Name/), {
      target: { value: 'Main Postgres' },
    })
    fireEvent.change(screen.getByLabelText(/^CIDRs/), {
      target: { value: '10.20.0.0/16\n10.30.0.0/24' },
    })
    fireEvent.change(screen.getByLabelText(/^Ports/), {
      target: { value: '5432, 53/udp' },
    })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create Destination/ }))
    await waitFor(() =>
      expect(endpoints.createEgressDestination).toHaveBeenCalledWith({
        cidrs: ['10.20.0.0/16', '10.30.0.0/24'],
        description: null,
        global: false,
        name: 'Main Postgres',
        organizations: ['acme'],
        ports: [
          { port: 5432, protocol: 'TCP' },
          { port: 53, protocol: 'UDP' },
        ],
        slug: 'main-postgres',
      }),
    )
  })

  it('shows the API error on save', async () => {
    vi.mocked(endpoints.listEgressDestinations).mockResolvedValue([
      destination(),
    ])
    vi.mocked(endpoints.updateEgressDestination).mockRejectedValue(
      new Error('CIDR 8.8.8.0/24 is not internal'),
    )
    mountAt('/admin/egress-destinations/pg-main/edit')
    fireEvent.click(await screen.findByRole('button', { name: /Save/ }))
    expect(
      await screen.findByText('Failed to save the destination'),
    ).toBeInTheDocument()
    expect(endpoints.updateEgressDestination).toHaveBeenCalledWith(
      'pg-main',
      expect.objectContaining({ cidrs: ['10.20.0.0/16'] }),
    )
  })

  it('parses ports', () => {
    expect(parsePorts('443 53/udp,8080/TCP')).toEqual([
      { port: 443, protocol: 'TCP' },
      { port: 53, protocol: 'UDP' },
      { port: 8080, protocol: 'TCP' },
    ])
    expect(parsePorts('70000')).toBeNull()
    expect(parsePorts('443/icmp')).toBeNull()
  })
})
