import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  createServiceAccountApiKey,
  revokeServiceAccountApiKey,
  rotateServiceAccountApiKey,
  createClientCredential,
  revokeClientCredential,
  rotateClientCredential,
  addServiceAccountToOrg,
  updateServiceAccountOrgRole,
  removeServiceAccountFromOrg,
} from '@/api/endpoints'
import type { ServiceAccount, ClientCredentialCreate } from '@/types'

export function useServiceAccountMutations(account: ServiceAccount) {
  const queryClient = useQueryClient()

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addServiceAccountToOrg(account.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to add to organization: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const updateOrgRoleMutation = useMutation({
    mutationFn: ({
      orgSlug,
      roleSlug,
    }: {
      orgSlug: string
      roleSlug: string
    }) =>
      updateServiceAccountOrgRole(account.slug, orgSlug, {
        role_slug: roleSlug,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to update role: ${extractApiErrorDetail(error)}`)
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) =>
      removeServiceAccountFromOrg(account.slug, orgSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to remove from organization: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const createApiKeyMutation = useMutation({
    mutationFn: (name: string) =>
      createServiceAccountApiKey(account.slug, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to create API key: ${extractApiErrorDetail(error)}`)
    },
  })

  const revokeApiKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      revokeServiceAccountApiKey(account.slug, keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to revoke API key: ${extractApiErrorDetail(error)}`)
    },
  })

  const rotateApiKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      rotateServiceAccountApiKey(account.slug, keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to rotate API key: ${extractApiErrorDetail(error)}`)
    },
  })

  const createCredentialMutation = useMutation({
    mutationFn: (data: ClientCredentialCreate) =>
      createClientCredential(account.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to create credential: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const revokeCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      revokeClientCredential(account.slug, clientId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to revoke credential: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const rotateCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      rotateClientCredential(account.slug, clientId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to rotate credential: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  return {
    addOrgMutation,
    updateOrgRoleMutation,
    removeOrgMutation,
    createApiKeyMutation,
    revokeApiKeyMutation,
    rotateApiKeyMutation,
    createCredentialMutation,
    revokeCredentialMutation,
    rotateCredentialMutation,
  }
}
