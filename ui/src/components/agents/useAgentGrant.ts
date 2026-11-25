import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  createSecretGrant,
  listSecretBindings,
  listSecretGrants,
  updateSecretGrant,
} from '@/api/endpoints'
import type {
  SecretBinding,
  SecretGrant,
  SecretGrantCreate,
} from '@/components/admin/secrets/types'
import { useHasPermission, useInTeam } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'

import { agentGrants, covers, grantFor, ownGrant } from './access'

export interface GrantAgent {
  id: string
  name: string
  team?: string
}

/**
 * The secret grants of an agent, and the grants that the user can add.
 * Grants apply at once; they are not part of the agent version.
 */
export function useAgentGrant(orgSlug: string, agent: GrantAgent | null) {
  const canReadGrants = useHasPermission('secret_grant:read', orgSlug)
  const canReadBindings = useHasPermission('secret_binding:read', orgSlug)
  const canRead = canReadGrants && canReadBindings
  // Without secret_binding:write, the API allows grants only to agents
  // of the user's teams, and only of grantable bindings (#871).
  const canWriteBindings = useHasPermission('secret_binding:write', orgSlug)
  const inTeam = useInTeam(orgSlug, agent?.team)
  const canWrite =
    useHasPermission('secret_grant:write', orgSlug) &&
    (canWriteBindings || inTeam)
  const mayGrant = (binding: SecretBinding) =>
    canWriteBindings || binding.grantable
  const canGrant = (binding: SecretBinding) =>
    Boolean(agent) && canRead && canWrite && mayGrant(binding)
  const queryClient = useQueryClient()
  const grants = useQuery({
    enabled: canRead,
    queryFn: ({ signal }) => listSecretGrants(orgSlug, signal),
    queryKey: ['secret-grants', orgSlug],
  })
  const bindings = useQuery({
    enabled: canRead,
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
  })
  // A new purpose goes on the agent's own grant of the binding, if it
  // has one, not on a second grant for the same secret.
  const save = useMutation({
    mutationFn: ({
      body,
      own,
    }: {
      body: SecretGrantCreate
      own?: SecretGrant
    }) =>
      own
        ? updateSecretGrant(orgSlug, own.id, {
            purposes: [...own.purposes, ...body.purposes],
          })
        : createSecretGrant(orgSlug, body),
    onError: (error) => toast.error(extractApiErrorDetail(error)),
    onSuccess: async () => {
      toast.success('Access granted')
      await queryClient.invalidateQueries({
        queryKey: ['secret-grants', orgSlug],
      })
    },
  })

  const mine = agent ? agentGrants(grants.data ?? [], agent.id) : []
  const ensure = (
    binding: SecretBinding,
    purpose: string,
    mode: SecretGrantCreate['delivery_modes'][number],
    done?: () => void,
  ) => {
    if (!agent || !canGrant(binding)) return
    if (covers(mine, binding.id, purpose, mode)) return
    save.mutate(
      {
        body: grantFor(agent, binding, purpose, mode),
        own: ownGrant(mine, binding.id, mode),
      },
      { onSuccess: done },
    )
  }

  return {
    bindings,
    canGrant,
    canRead,
    canWrite,
    ensure,
    grants,
    mayGrant,
    mine,
    save,
  }
}
