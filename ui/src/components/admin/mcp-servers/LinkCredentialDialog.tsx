import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  linkMcpServerCredential,
  listAgents,
  listSecretProviders,
} from '@/api/endpoints'
import { queryKeys } from '@/lib/queryKeys'
import type { MCPServer, MCPServerCredentialBinding } from '@/types'

import { SecretDialog } from '../secrets/SecretDialog'

interface LinkCredentialDialogProps {
  // The reference in the form, which can differ from the saved one.
  credentialRef: string
  onClose: () => void
  onLinked: (credentialRef: null | string) => void
  orgSlug: string
  server: MCPServer
}

/**
 * Link the server's credential for agents in one organization: the API
 * makes a broker binding, a grant for the agents, and sets
 * `credential_ref`. The secret value must already be in the provider.
 */
export function LinkCredentialDialog({
  credentialRef,
  onClose,
  onLinked,
  orgSlug,
  server,
}: LinkCredentialDialogProps) {
  const queryClient = useQueryClient()
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })
  const agentsQuery = useQuery({
    queryFn: ({ signal }) => listAgents(orgSlug, signal),
    queryKey: queryKeys.agents(orgSlug),
  })
  const mutation = useMutation({
    mutationFn: (body: MCPServerCredentialBinding) =>
      linkMcpServerCredential(server.id, body),
    onSuccess: (result) => {
      toast.success(`Linked ${result.server.credential_ref}`)
      onLinked(result.server.credential_ref ?? null)
      void queryClient.invalidateQueries({ queryKey: ['mcp-servers'] })
      void queryClient.invalidateQueries({
        queryKey: ['secret-bindings', orgSlug],
      })
      void queryClient.invalidateQueries({
        queryKey: ['secret-grants', orgSlug],
      })
    },
  })

  return (
    <SecretDialog
      description={`Bind the credential of ${server.name} in ${orgSlug} and allow agents to use it. Put the value in the provider first: the binding holds no secret.`}
      error={mutation.error}
      fields={[
        {
          description: 'secret://<scope>/<path>, lower case, no field',
          initial: credentialRef.split('#')[0],
          kind: 'text',
          label: 'Reference',
          name: 'reference',
          required: true,
        },
        {
          description:
            'The field of the secret that holds the value. Empty: the whole value.',
          initial: credentialRef.split('#')[1] ?? '',
          kind: 'text',
          label: 'Field',
          name: 'field',
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
          description:
            'For AWS: {"secret_id": "prod/app", "version_stage": "AWSCURRENT"}',
          initial: '{}',
          kind: 'json',
          label: 'Locator',
          name: 'locator',
          required: true,
        },
        {
          // An empty list is a decision only when the agents are known.
          description: agentsQuery.isError
            ? 'Could not load the agents.'
            : agentsQuery.isPending
              ? 'Loading agents…'
              : 'Empty: no grant is made.',
          kind: 'multi',
          label: 'Agents',
          name: 'agent_ids',
          options: (agentsQuery.data ?? []).map((a) => ({
            label: a.name,
            value: a.id,
          })),
        },
        {
          initial: '900',
          kind: 'number',
          label: 'Maximum TTL (seconds)',
          name: 'max_ttl_seconds',
        },
      ]}
      isPending={mutation.isPending || !agentsQuery.isSuccess}
      onClose={onClose}
      onSubmit={(body) =>
        mutation.mutate({
          ...(body as unknown as MCPServerCredentialBinding),
          organization: orgSlug,
        })
      }
      title="Link credential for agents"
    />
  )
}
