import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createSecretBinding,
  deleteSecretBinding,
  listSecretBindings,
  listSecretProviders,
  updateSecretBinding,
  validateSecretBinding,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'

import { SecretDialog } from './SecretDialog'
import {
  CREDENTIAL_CLASSES,
  DELIVERY_MODES,
  type SecretBinding,
  type SecretBindingCreate,
} from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

const asOptions = (values: readonly string[]) =>
  values.map((value) => ({ label: value, value }))

// fallow-ignore-next-line complexity
export function BindingsTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const queryKey = ['secret-bindings', orgSlug]
  const bindingsQuery = useQuery({
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey,
  })
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })
  const providerNames = new Map(
    (providersQuery.data ?? []).map((p) => [p.id, p.name]),
  )
  const refresh = () => queryClient.invalidateQueries({ queryKey })

  const createMutation = useMutation({
    mutationFn: (body: SecretBindingCreate) =>
      createSecretBinding(orgSlug, body),
    onSuccess: () => {
      setCreating(false)
      void refresh()
    },
  })
  const enableMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) =>
      updateSecretBinding(orgSlug, id, { enabled }),
    onError,
    onSuccess: refresh,
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSecretBinding(orgSlug, id),
    onError,
    onSuccess: refresh,
  })
  const validateMutation = useMutation({
    mutationFn: (id: string) => validateSecretBinding(orgSlug, id),
    onError,
    onSuccess: (result) =>
      result.valid
        ? toast.success('The provider has the bound secret')
        : toast.error(`Not valid: ${result.reason ?? 'unknown'}`),
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>New binding</Button>
      </div>
      <AdminTable<SecretBinding>
        actions={(row) => (
          <Button
            disabled={validateMutation.isPending}
            onClick={() => validateMutation.mutate(row.id)}
            size="sm"
            variant="outline"
          >
            Validate
          </Button>
        )}
        columns={[
          {
            header: 'Reference',
            key: 'reference',
            render: (row) => (
              <span className="font-mono text-xs">{row.reference}</span>
            ),
          },
          {
            header: 'Provider',
            key: 'provider',
            render: (row) => providerNames.get(row.provider_id) ?? '—',
          },
          {
            header: 'Class',
            key: 'class',
            render: (row) => row.credential_class,
          },
          {
            header: 'Fields',
            key: 'fields',
            render: (row) => row.allowed_fields.join(', ') || 'Whole value',
          },
          {
            header: 'Delivery',
            key: 'delivery',
            render: (row) => row.allowed_delivery_modes.join(', '),
          },
          {
            cellAlign: 'right',
            header: 'Max TTL',
            headerAlign: 'right',
            key: 'ttl',
            render: (row) => `${row.max_ttl_seconds}s`,
          },
          {
            header: 'Enabled',
            interactive: true,
            key: 'enabled',
            render: (row) => (
              <Switch
                aria-label={`Enable ${row.reference}`}
                checked={row.enabled}
                onCheckedChange={(enabled) =>
                  enableMutation.mutate({ enabled, id: row.id })
                }
              />
            ),
          },
        ]}
        emptyMessage="No secret bindings."
        getRowKey={(row) => row.id}
        getRowLabel={(row) => row.reference}
        isDeleting={deleteMutation.isPending}
        loading={bindingsQuery.isLoading}
        onDelete={(row) => deleteMutation.mutate(row.id)}
        rows={bindingsQuery.data ?? []}
      />
      {creating && (
        <SecretDialog
          description="Map a logical reference to a location in a provider. A binding holds no secret value."
          error={createMutation.error}
          fields={[
            {
              description: 'secret://<scope>/<path>, lower case, no field',
              kind: 'text',
              label: 'Reference',
              name: 'reference',
              required: true,
            },
            {
              kind: 'select',
              label: 'Provider',
              name: 'provider_id',
              options: (providersQuery.data ?? []).map((p) => ({
                label: p.name,
                value: p.id,
              })),
              required: true,
            },
            {
              initial: 'static',
              kind: 'select',
              label: 'Credential class',
              name: 'credential_class',
              options: asOptions(CREDENTIAL_CLASSES),
              required: true,
            },
            {
              description:
                'For AWS: {"secret_id": "prod/app", "version_stage": "AWSCURRENT"}',
              initial: '{}',
              kind: 'json',
              label: 'Locator',
              name: 'locator',
              required: true,
            },
            {
              description:
                'Comma separated. Empty: only the whole value is allowed.',
              kind: 'list',
              label: 'Allowed fields',
              name: 'allowed_fields',
            },
            {
              kind: 'multi',
              label: 'Allowed delivery modes',
              name: 'allowed_delivery_modes',
              options: asOptions(DELIVERY_MODES),
              required: true,
            },
            {
              initial: '900',
              kind: 'number',
              label: 'Maximum TTL (seconds)',
              name: 'max_ttl_seconds',
            },
            { kind: 'text', label: 'Description', name: 'description' },
          ]}
          isPending={createMutation.isPending}
          onClose={() => setCreating(false)}
          onSubmit={(body) =>
            createMutation.mutate(body as unknown as SecretBindingCreate)
          }
          title="New binding"
        />
      )}
    </div>
  )
}
