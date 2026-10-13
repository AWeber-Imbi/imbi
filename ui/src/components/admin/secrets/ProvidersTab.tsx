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
import { AdminTable } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'

import { SecretDialog } from './SecretDialog'
import type { SecretProvider, SecretProviderCreate } from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

// fallow-ignore-next-line complexity
export function ProvidersTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const queryKey = ['secret-providers', orgSlug]
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey,
  })
  const typesQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviderTypes(orgSlug, signal),
    queryKey: ['secret-provider-types', orgSlug],
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey })

  const createMutation = useMutation({
    mutationFn: (body: SecretProviderCreate) =>
      createSecretProvider(orgSlug, body),
    onSuccess: () => {
      setCreating(false)
      void refresh()
    },
  })
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
        <Button onClick={() => setCreating(true)}>New provider</Button>
      </div>
      <AdminTable<SecretProvider>
        actions={(row) => (
          <Button
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate(row.id)}
            size="sm"
            variant="outline"
          >
            Test
          </Button>
        )}
        columns={[
          { header: 'Name', key: 'name', render: (row) => row.name },
          {
            header: 'Type',
            key: 'type',
            render: (row) => <span className="font-mono">{row.type}</span>,
          },
          {
            header: 'Health',
            key: 'health',
            render: (row) =>
              row.health_status ? (
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
            render: (row) => <RelativeTime value={row.health_checked_at} />,
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
      {creating && (
        <SecretDialog
          description="An adapter to an external secret system. The configuration holds no credentials: imbi-api uses its workload identity."
          error={createMutation.error}
          fields={[
            {
              description: 'Lower case letters, digits, - and _',
              kind: 'text',
              label: 'Name',
              name: 'name',
              required: true,
            },
            {
              kind: 'select',
              label: 'Type',
              name: 'type',
              options: (typesQuery.data ?? []).map((t) => ({
                label: t.label,
                value: t.type,
              })),
              required: true,
            },
            {
              description:
                'For AWS: {"region": "us-east-1", "role_arn": "..."}. role_arn is required; its trust policy must require sts:ExternalId "imbi:<organization id>". No access keys.',
              initial: '{}',
              kind: 'json',
              label: 'Configuration',
              name: 'config',
            },
          ]}
          isPending={createMutation.isPending}
          onClose={() => setCreating(false)}
          onSubmit={(body) =>
            createMutation.mutate(body as unknown as SecretProviderCreate)
          }
          title="New provider"
        />
      )}
    </div>
  )
}
