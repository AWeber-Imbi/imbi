import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createSecretProvider,
  deleteSecretProvider,
  listSecretProviders,
  listSecretProviderTypes,
  testSecretProvider,
  updateSecretProvider,
} from '@/api/endpoints'
import { toTitleCase } from '@/components/admin/blueprints/blueprint-schema-utils'
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'

import { CopyId } from './CopyId'
import { ProviderDialog } from './ProviderDialog'
import type {
  SecretProvider,
  SecretProviderCreate,
  SecretProviderPatch,
} from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

// fallow-ignore-next-line complexity
export function ProvidersTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  // 'new' for the create form, a row for the edit form.
  const [editing, setEditing] = useState<'new' | null | SecretProvider>(null)
  const queryKey = ['secret-providers', orgSlug]
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey,
  })
  const typesQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviderTypes(orgSlug, signal),
    queryKey: ['secret-provider-types', orgSlug],
  })
  const typeLabels = new Map(
    (typesQuery.data ?? []).map((t) => [t.type, t.label]),
  )
  const refresh = () => queryClient.invalidateQueries({ queryKey })

  const saveMutation = useMutation({
    mutationFn: ({
      body,
      id,
    }: {
      body: Record<string, unknown>
      id?: string
    }) =>
      id
        ? updateSecretProvider(orgSlug, id, body as SecretProviderPatch)
        : createSecretProvider(orgSlug, body as SecretProviderCreate),
    onSuccess: () => void refresh(),
  })
  const open = (target: 'new' | SecretProvider) => {
    saveMutation.reset()
    setEditing(target)
  }
  const row = editing === 'new' ? undefined : (editing ?? undefined)
  const enableMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) =>
      updateSecretProvider(orgSlug, id, { enabled }),
    onError,
    onSuccess: refresh,
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSecretProvider(orgSlug, id),
    onError,
    onSuccess: refresh,
  })
  const testMutation = useMutation({
    mutationFn: (id: string) => testSecretProvider(orgSlug, id),
    onError,
    onSuccess: (result) => {
      if (result.status === 'healthy') {
        toast.success('Provider is healthy')
      } else {
        toast.error(`Provider is unhealthy: ${result.reason ?? 'unknown'}`)
      }
      void refresh()
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => open('new')}>New provider</Button>
      </div>
      <AdminTable<SecretProvider>
        actions={(row) => (
          <>
            <Button onClick={() => open(row)} size="sm" variant="outline">
              Edit
            </Button>
            <Button
              disabled={testMutation.isPending || !canTest(row)}
              onClick={() => testMutation.mutate(row.id)}
              size="sm"
              title={
                canTest(row) ? undefined : 'This provider type has no test'
              }
              variant="outline"
            >
              Test
            </Button>
          </>
        )}
        columns={[
          { header: 'Name', key: 'name', render: (row) => row.name },
          {
            header: 'Id',
            interactive: true,
            key: 'id',
            render: (row) => <CopyId id={row.id} />,
          },
          {
            header: 'Type',
            key: 'type',
            render: (row) => typeLabels.get(row.type) ?? toTitleCase(row.type),
          },
          {
            header: 'Health',
            key: 'health',
            render: (row) =>
              !canTest(row) ? (
                <span className="text-tertiary">No test</span>
              ) : row.health_status ? (
                <Badge
                  variant={
                    row.health_status === 'healthy' ? 'success' : 'danger'
                  }
                >
                  {row.health_reason ?? row.health_status}
                </Badge>
              ) : (
                <span className="text-tertiary">Not tested</span>
              ),
          },
          {
            header: 'Checked',
            key: 'checked',
            render: (row) =>
              canTest(row) ? (
                <RelativeTime value={row.health_checked_at} />
              ) : (
                <span className="text-tertiary">—</span>
              ),
          },
          {
            header: 'Enabled',
            interactive: true,
            key: 'enabled',
            render: (row) => (
              <Switch
                aria-label={`Enable ${row.name}`}
                checked={row.enabled}
                onCheckedChange={(enabled) =>
                  enableMutation.mutate({ enabled, id: row.id })
                }
              />
            ),
          },
        ]}
        emptyMessage="No secret providers."
        getRowKey={(row) => row.id}
        getRowLabel={(row) => row.name}
        isDeleting={deleteMutation.isPending}
        loading={providersQuery.isLoading}
        onDelete={(row) => deleteMutation.mutate(row.id)}
        rows={providersQuery.data ?? []}
      />
      {editing && (
        <ProviderDialog
          error={saveMutation.error}
          isPending={saveMutation.isPending}
          onClose={() => setEditing(null)}
          onSubmit={(body) =>
            // Close in a per-call callback: open() resets the mutation,
            // so a stale save does not close a newer dialog.
            saveMutation.mutate(
              { body, id: row?.id },
              { onSuccess: () => setEditing(null) },
            )
          }
          original={row}
          types={typesQuery.data ?? []}
        />
      )}
    </div>
  )
}

/** Whether the provider type has a health check that Test can run. */
const canTest = (row: SecretProvider) =>
  row.capabilities.includes('health_check')
