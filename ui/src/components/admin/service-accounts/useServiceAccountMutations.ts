import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  addServiceAccountToOrg,
  createClientCredential,
  createServiceAccountApiKey,
  getUploadUrl,
  removeServiceAccountFromOrg,
  revokeClientCredential,
  revokeServiceAccountApiKey,
  rotateClientCredential,
  rotateServiceAccountApiKey,
  updateServiceAccount,
  updateServiceAccountOrgRole,
  uploadFile,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildReplacePatch } from '@/lib/json-patch'
import type { ClientCredentialCreate, ServiceAccount } from '@/types'

export function useServiceAccountMutations(account: ServiceAccount) {
  const queryClient = useQueryClient()

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addServiceAccountToOrg(account.slug, data),
    onError: (error: unknown) => {
      toast.error(
        `Failed to add to organization: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
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
      updateServiceAccountOrgRole(
        account.slug,
        orgSlug,
        buildReplacePatch({ role_slug: roleSlug }),
      ),
    onError: (error: unknown) => {
      toast.error(`Failed to update role: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) =>
      removeServiceAccountFromOrg(account.slug, orgSlug),
    onError: (error: unknown) => {
      toast.error(
        `Failed to remove from organization: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
  })

  const createApiKeyMutation = useMutation({
    mutationFn: (name: string) =>
      createServiceAccountApiKey(account.slug, { name }),
    onError: (error: unknown) => {
      toast.error(`Failed to create API key: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
  })

  const revokeApiKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      revokeServiceAccountApiKey(account.slug, keyId),
    onError: (error: unknown) => {
      toast.error(`Failed to revoke API key: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
  })

  const rotateApiKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      rotateServiceAccountApiKey(account.slug, keyId),
    onError: (error: unknown) => {
      toast.error(`Failed to rotate API key: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
  })

  const createCredentialMutation = useMutation({
    mutationFn: (data: ClientCredentialCreate) =>
      createClientCredential(account.slug, data),
    onError: (error: unknown) => {
      toast.error(
        `Failed to create credential: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
  })

  const revokeCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      revokeClientCredential(account.slug, clientId),
    onError: (error: unknown) => {
      toast.error(
        `Failed to revoke credential: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
  })

  const rotateCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      rotateClientCredential(account.slug, clientId),
    onError: (error: unknown) => {
      toast.error(
        `Failed to rotate credential: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
  })

  const uploadAvatarMutation = useMutation({
    mutationFn: async (file: File) => {
      const upload = await uploadFile(file)
      const avatarUrl = getUploadUrl(upload.id)
      return updateServiceAccount(
        account.slug,
        buildReplacePatch({ avatar_url: avatarUrl }),
      )
    },
    onError: (error: unknown) => {
      toast.error(`Failed to upload avatar: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
  })

  const removeAvatarMutation = useMutation({
    mutationFn: () =>
      updateServiceAccount(
        account.slug,
        buildReplacePatch({ avatar_url: null }),
      ),
    onError: (error: unknown) => {
      toast.error(`Failed to remove avatar: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
  })

  return {
    addOrgMutation,
    createApiKeyMutation,
    createCredentialMutation,
    removeAvatarMutation,
    removeOrgMutation,
    revokeApiKeyMutation,
    revokeCredentialMutation,
    rotateApiKeyMutation,
    rotateCredentialMutation,
    updateOrgRoleMutation,
    uploadAvatarMutation,
  }
}
