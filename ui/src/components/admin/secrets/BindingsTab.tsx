import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createSecretBinding,
  deleteSecretBinding,
  listSecretBindings,
  listSecretProviders,
  listSecretProviderTypes,
  updateSecretBinding,
  validateSecretBinding,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'

import { BindingDialog } from './BindingDialog'
import { CopyId } from './CopyId'
import {
  type SecretBinding,
  type SecretBindingCreate,
  type SecretBindingPatch,
  titleList,
} from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

interface KeyUsage {
  app_id: string
  consumers?: string[]
  host: string
}

// fallow-ignore-next-line complexity
export function BindingsTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  // 'new' for the create form, a row for the edit form.
  const [editing, setEditing] = useState<'new' | null | SecretBinding>(null)
  const queryKey = ['secret-bindings', orgSlug]
  const bindingsQuery = useQuery({
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey,
  })
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })
  const typesQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviderTypes(orgSlug, signal),
    queryKey: ['secret-provider-types', orgSlug],
  })
  const providerNames = new Map(
    (providersQuery.data ?? []).map((p) => [p.id, p.name]),
  )
  // The GitHub host of each github_app provider, by provider id.
  const appProviders = new Map(
    (providersQuery.data ?? [])
      .filter((p) => p.type === 'github_app')
      .map((p) => [p.id, String(p.config.host ?? 'github.com')]),
  )
  const bindings = bindingsQuery.data ?? []
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
        ? updateSecretBinding(orgSlug, id, body as SecretBindingPatch)
        : createSecretBinding(orgSlug, body as SecretBindingCreate),
    onSuccess: () => void refresh(),
  })
  const open = (target: 'new' | SecretBinding) => {
    saveMutation.reset()
    setEditing(target)
  }
  const row = editing === 'new' ? undefined : (editing ?? undefined)
  const linkMutation = useMutation({
    mutationFn: ({ app, key, usage }: ReturnType<typeof unlinkedKeys>[0]) =>
      updateSecretBinding(orgSlug, key.id, {
        provider_key_usage: {
          ...usage,
          consumers: [...(usage.consumers ?? []), app.id],
        },
      }),
    onError,
    onSuccess: refresh,
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
        <Button onClick={() => open('new')}>New binding</Button>
      </div>
      {unlinkedKeys(bindings, appProviders).map((link) => (
        <Alert
          key={link.app.id}
          title="The key does not list this binding as a consumer"
          variant="warning"
        >
          <div className="flex items-center justify-between gap-4">
            <span>
              <span className="font-mono text-xs">{link.app.reference}</span>{' '}
              signs with{' '}
              <span className="font-mono text-xs">{link.key.reference}</span>.
              The broker refuses the key until it lists the binding.
            </span>
            <Button
              disabled={linkMutation.isPending}
              onClick={() => linkMutation.mutate(link)}
              size="sm"
              variant="outline"
            >
              Add as consumer
            </Button>
          </div>
        </Alert>
      ))}
      <AdminTable<SecretBinding>
        actions={(row) => (
          <>
            <Button onClick={() => open(row)} size="sm" variant="outline">
              Edit
            </Button>
            <Button
              disabled={validateMutation.isPending}
              onClick={() => validateMutation.mutate(row.id)}
              size="sm"
              variant="outline"
            >
              Validate
            </Button>
          </>
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
            header: 'Id',
            interactive: true,
            key: 'id',
            render: (row) => <CopyId id={row.id} />,
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
            render: (row) =>
              titleList(row.allowed_delivery_modes) +
              (row.allowed_delivery_targets.length
                ? ` (${row.allowed_delivery_targets.join(', ')})`
                : ''),
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
        rows={bindings}
      />
      {editing && (
        <BindingDialog
          consumers={bindings
            .filter((b) => {
              const usage = row?.provider_key_usage as KeyUsage | undefined
              // Keep current consumers so the admin can remove them.
              if (usage?.consumers?.includes(b.id)) return true
              if (
                b.credential_class !== 'dynamic' ||
                !appProviders.has(b.provider_id)
              )
                return false
              // A key with no saved host and App id offers each App.
              // Otherwise offer only the Apps that the broker accepts.
              return (
                !usage?.host ||
                (usage.host === appProviders.get(b.provider_id) &&
                  usage.app_id === String(b.locator.app_id))
              )
            })
            .map((b) => ({ label: b.reference, value: b.id }))}
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
          orgSlug={orgSlug}
          original={row}
          providers={providersQuery.data ?? []}
          providerTypes={typesQuery.data ?? []}
        />
      )}
    </div>
  )
}

/**
 * Each binding whose locator names a provider key (a GitHub App
 * private_key) for its host and App id that does not list the binding
 * as a consumer. The broker refuses the key to such a binding. A key
 * for a different host or App is not offered, because the broker
 * refuses it also when the binding is a consumer.
 */
function unlinkedKeys(
  bindings: SecretBinding[],
  appHosts: Map<string, string>,
) {
  return bindings.flatMap((app) => {
    const privateKey = app.locator.private_key
    if (app.credential_class !== 'dynamic' || typeof privateKey !== 'string')
      return []
    const key = bindings.find(
      (b) => b.reference === privateKey.split('#')[0] && b.provider_key_usage,
    )
    const usage = key?.provider_key_usage as KeyUsage | undefined
    if (!key || !usage || usage.consumers?.includes(app.id)) return []
    if (
      usage.host !== appHosts.get(app.provider_id) ||
      usage.app_id !== String(app.locator.app_id)
    )
      return []
    return [{ app, key, usage }]
  })
}
