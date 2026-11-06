import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  deleteWorkloadIdentity,
  getWorkloadIdentity,
  listIdentitySourceTypes,
  putWorkloadIdentity,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { extractApiErrorDetail } from '@/lib/apiError'

import { SecretDialog } from './SecretDialog'
import type { WorkloadIdentity, WorkloadIdentityPut } from './types'

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

/**
 * The identity source of the organization (WIF plan 4.1). imbi-api gets
 * an identity JWT from it for each vendor token exchange. One source for
 * each organization: saving replaces it.
 */
export function IdentityTab({ orgSlug }: { orgSlug: string }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const queryKey = ['workload-identity', orgSlug]
  const identityQuery = useQuery({
    queryFn: ({ signal }) => getWorkloadIdentity(orgSlug, signal),
    queryKey,
  })
  const typesQuery = useQuery({
    // Only the dialog uses the types.
    enabled: editing,
    queryFn: ({ signal }) => listIdentitySourceTypes(orgSlug, signal),
    queryKey: ['identity-source-types', orgSlug],
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey })
  const current = identityQuery.data ?? undefined

  const saveMutation = useMutation({
    mutationFn: (body: WorkloadIdentityPut) =>
      putWorkloadIdentity(orgSlug, body),
    onSuccess: () => void refresh(),
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteWorkloadIdentity(orgSlug),
    onError,
    onSuccess: refresh,
  })
  const open = () => {
    saveMutation.reset()
    setEditing(true)
  }

  return (
    <div className="space-y-4">
      {!current && (
        <div className="flex justify-end">
          <Button onClick={open}>Set identity source</Button>
        </div>
      )}
      <AdminTable<WorkloadIdentity>
        actions={() => (
          <Button onClick={open} size="sm" variant="outline">
            Edit
          </Button>
        )}
        columns={[
          {
            header: 'Type',
            key: 'type',
            render: (row) => <span className="font-mono">{row.type}</span>,
          },
          {
            header: 'Configuration',
            key: 'config',
            render: (row) => (
              <span className="font-mono">{JSON.stringify(row.config)}</span>
            ),
          },
          {
            header: 'Updated by',
            key: 'updated_by',
            render: (row) => row.updated_by,
          },
          {
            header: 'Updated',
            key: 'updated_at',
            render: (row) => <RelativeTime value={row.updated_at} />,
          },
        ]}
        emptyMessage="No identity source. Workload identity federation is off for this organization."
        getRowKey={(row) => row.type}
        getRowLabel={(row) => `the ${row.type} identity source`}
        isDeleting={deleteMutation.isPending}
        loading={identityQuery.isLoading}
        onDelete={() => deleteMutation.mutate()}
        rows={current ? [current] : []}
      />
      {editing && (
        <SecretDialog
          description="Where imbi-api gets the identity JWT that it exchanges for a vendor access token. Saving checks the configuration with one call to the source."
          error={saveMutation.error}
          fields={[
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
                'For AWS STS: {"region": "us-east-1", "role_arn": "arn:aws:iam::<account>:role/<identity role>"}. The trust policy of the role must require sts:ExternalId "imbi:<organization id>". No access keys.',
              initial: '{}',
              kind: 'json',
              label: 'Configuration',
              name: 'config',
            },
          ]}
          isPending={saveMutation.isPending}
          onClose={() => setEditing(false)}
          onSubmit={(body) =>
            // The API replaces the whole source; an edit sends only the
            // changed fields, so fill in the others.
            saveMutation.mutate(
              {
                ...(current && { config: current.config, type: current.type }),
                ...body,
              } as WorkloadIdentityPut,
              { onSuccess: () => setEditing(false) },
            )
          }
          original={current}
          title={current ? 'Edit identity source' : 'Set identity source'}
        />
      )}
    </div>
  )
}
