import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createSecretGrant,
  deleteSecretGrant,
  listAgents,
  listSecretBindings,
  listSecretGrants,
  updateSecretGrant,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

import { SecretDialog } from './SecretDialog'
import {
  DELIVERY_MODES,
  type SecretGrant,
  type SecretGrantCreate,
} from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

// fallow-ignore-next-line complexity
export function GrantsTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const queryKey = ['secret-grants', orgSlug]
  const grantsQuery = useQuery({
    queryFn: ({ signal }) => listSecretGrants(orgSlug, signal),
    queryKey,
  })
  const bindingsQuery = useQuery({
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
  })
  const agentsQuery = useQuery({
    queryFn: ({ signal }) => listAgents(orgSlug, signal),
    queryKey: queryKeys.agents(orgSlug),
  })
  const references = new Map(
    (bindingsQuery.data ?? []).map((b) => [b.id, b.reference]),
  )
  const agentNames = new Map(
    (agentsQuery.data ?? []).map((a) => [a.id, a.name]),
  )
  const refresh = () => queryClient.invalidateQueries({ queryKey })

  const createMutation = useMutation({
    mutationFn: (body: SecretGrantCreate) => createSecretGrant(orgSlug, body),
    onSuccess: () => {
      setCreating(false)
      void refresh()
    },
  })
  const enableMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) =>
      updateSecretGrant(orgSlug, id, { enabled }),
    onError,
    onSuccess: refresh,
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSecretGrant(orgSlug, id),
    onError,
    onSuccess: refresh,
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>New grant</Button>
      </div>
      <AdminTable<SecretGrant>
        columns={[
          {
            header: 'Agents',
            key: 'agents',
            render: (row) =>
              row.agent_ids.map((id) => agentNames.get(id) ?? id).join(', '),
          },
          {
            header: 'Bindings',
            key: 'bindings',
            render: (row) => (
              <span className="font-mono text-xs">
                {row.binding_ids
                  .map((id) => references.get(id) ?? id)
                  .join(', ')}
              </span>
            ),
          },
          {
            header: 'Projects',
            key: 'projects',
            render: (row) => row.project_ids.join(', ') || 'Any',
          },
          {
            header: 'Purposes',
            key: 'purposes',
            render: (row) => row.purposes.join(', '),
          },
          {
            header: 'Delivery',
            key: 'delivery',
            render: (row) => row.delivery_modes.join(', '),
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
                aria-label="Enable grant"
                checked={row.enabled}
                onCheckedChange={(enabled) =>
                  enableMutation.mutate({ enabled, id: row.id })
                }
              />
            ),
          },
        ]}
        emptyMessage="No secret grants. Without a grant, every request is denied."
        getRowKey={(row) => row.id}
        getRowLabel={(row) => row.description || 'this grant'}
        isDeleting={deleteMutation.isPending}
        loading={grantsQuery.isLoading}
        onDelete={(row) => deleteMutation.mutate(row.id)}
        rows={grantsQuery.data ?? []}
      />
      {creating && (
        <SecretDialog
          description="Exactly one enabled grant must allow a request, or the broker denies it. Ids are exact."
          error={createMutation.error}
          fields={[
            {
              kind: 'multi',
              label: 'Agents',
              name: 'agent_ids',
              options: (agentsQuery.data ?? []).map((a) => ({
                label: a.name,
                value: a.id,
              })),
              required: true,
            },
            {
              kind: 'multi',
              label: 'Bindings',
              name: 'binding_ids',
              options: (bindingsQuery.data ?? []).map((b) => ({
                label: b.reference,
                value: b.id,
              })),
              required: true,
            },
            {
              description:
                'Comma separated project ids. Empty allows any project.',
              kind: 'list',
              label: 'Projects',
              name: 'project_ids',
            },
            {
              description: 'Comma separated, e.g. github_write, checkout',
              kind: 'list',
              label: 'Purposes',
              name: 'purposes',
              required: true,
            },
            {
              kind: 'multi',
              label: 'Delivery modes',
              name: 'delivery_modes',
              options: DELIVERY_MODES.map((m) => ({ label: m, value: m })),
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
            createMutation.mutate(body as unknown as SecretGrantCreate)
          }
          title="New grant"
        />
      )}
    </div>
  )
}
