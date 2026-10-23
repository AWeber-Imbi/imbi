import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import {
  createEgressDestination,
  deleteEgressDestination,
  getEgressSyncStatus,
  listEgressDestinations,
  updateEgressDestination,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import type { EgressDestination, EgressDestinationCreate } from '@/types'

import { AdminSection } from './AdminSection'
import { EgressDestinationForm } from './egress-destinations/EgressDestinationForm'
import { formatPorts } from './egress-destinations/ports'

/**
 * The egress destinations of the harness runners (platform
 * administrators). A destination is pending until the egress sync
 * makes the network policy of its current generation.
 */
export function EgressDestinationManagement() {
  const { editPath, goToCreate, goToList, slug, viewMode } = useAdminNav()
  const [search, setSearch] = useState('')
  const sync = useQuery({
    queryFn: ({ signal }) => getEgressSyncStatus(signal),
    queryKey: queryKeys.egressSyncStatus(),
  })
  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items,
    updateMutation,
  } = useAdminCrud<
    EgressDestination,
    EgressDestinationCreate,
    EgressDestinationCreate,
    string
  >({
    createFn: (body) => createEgressDestination(body),
    deleteErrorLabel: 'egress destination',
    deleteFn: (slug) => deleteEgressDestination(slug),
    extraInvalidateKeys: [['egressDestinationChanges']],
    listFn: (signal) => listEgressDestinations(undefined, signal),
    onMutationSuccess: goToList,
    queryKey: queryKeys.egressDestinations(''),
    // The API compares the values: an unchanged field changes nothing.
    updateFn: ({ slug, ...body }) => updateEgressDestination(slug, body),
  })

  if (viewMode === 'create' || viewMode === 'edit') {
    const mutation = viewMode === 'create' ? createMutation : updateMutation
    const destination = items.find((d) => d.slug === slug) ?? null
    if (viewMode === 'edit' && !destination) {
      return <p className="text-tertiary text-sm">Loading…</p>
    }
    return (
      <EgressDestinationForm
        destination={destination}
        error={mutation.error}
        isLoading={mutation.isPending}
        onCancel={goToList}
        onSave={(body) => mutation.mutate(body)}
      />
    )
  }

  const query = search.toLowerCase()
  const rows = items.filter(
    (d) =>
      d.slug.includes(query) ||
      d.name.toLowerCase().includes(query) ||
      d.cidrs.some((c) => c.includes(query)),
  )

  return (
    <AdminSection
      createLabel="New Destination"
      error={error}
      errorTitle="Failed to load egress destinations"
      headerExtras={
        <span className="text-tertiary text-xs whitespace-nowrap">
          Last sync:{' '}
          {sync.data?.synced_at
            ? formatRelativeDate(sync.data.synced_at)
            : sync.isLoading
              ? '…'
              : 'never'}
        </span>
      }
      onCreate={goToCreate}
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search destinations..."
    >
      <AdminTable
        canDelete={(d) =>
          d.agents.length
            ? {
                allowed: false,
                reason: `Used by ${d.agents
                  .map((a) => `${a.organization_slug}/${a.slug}`)
                  .join(', ')}`,
              }
            : { allowed: true }
        }
        columns={[
          {
            header: 'Destination',
            key: 'name',
            render: (d) => (
              <div>
                <div className="text-primary">{d.name}</div>
                <div className="text-tertiary font-mono text-xs">{d.slug}</div>
              </div>
            ),
          },
          {
            header: 'CIDRs',
            key: 'cidrs',
            render: (d) => (
              <span className="font-mono text-xs">{d.cidrs.join(', ')}</span>
            ),
          },
          {
            header: 'Ports',
            key: 'ports',
            render: (d) => (
              <span className="font-mono text-xs">{formatPorts(d.ports)}</span>
            ),
          },
          {
            header: 'Scope',
            key: 'scope',
            render: (d) =>
              d.global ? (
                <Badge variant="info">global</Badge>
              ) : (
                <span className="text-secondary text-xs">
                  {d.organizations.join(', ') || 'all organizations'}
                </span>
              ),
          },
          {
            header: 'Generation',
            key: 'generation',
            render: (d) => (
              <span className="flex items-center gap-2 font-mono text-xs">
                g{d.generation}
                {d.pending && (
                  <Badge
                    title={`Applied: ${d.applied_generation == null ? 'none' : `g${d.applied_generation}`}`}
                    variant="warning"
                  >
                    pending
                  </Badge>
                )}
              </span>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Agents',
            headerAlign: 'right',
            key: 'agents',
            render: (d) => d.agents.length,
          },
        ]}
        emptyMessage={
          search
            ? 'No destinations match your search.'
            : 'No egress destinations yet.'
        }
        getDeleteLabel={(d) => d.name}
        getRowHref={(d) => editPath(d.slug)}
        getRowKey={(d) => d.slug}
        isDeleting={deleteMutation.isPending}
        loading={isLoading}
        onDelete={(d) => deleteMutation.mutate(d.slug)}
        rows={rows}
      />
    </AdminSection>
  )
}
