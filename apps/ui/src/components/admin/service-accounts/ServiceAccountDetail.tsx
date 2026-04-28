import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Calendar, Clock, Edit2, Power, Tag } from 'lucide-react'

import { getRoles } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import type {
  ApiKeyCreated,
  ClientCredentialCreated,
  ServiceAccount,
} from '@/types'

import { ApiKeysSection } from './ApiKeysSection'
import { ClientCredentialsSection } from './ClientCredentialsSection'
import { OrgMembershipsCard } from './OrgMembershipsCard'
import { useServiceAccountMutations } from './useServiceAccountMutations'

type ConfirmState =
  | null
  | { action: 'remove-org'; orgName: string; orgSlug: string }
  | { action: 'revoke-credential'; clientId: string }
  | { action: 'revoke-key'; keyId: string }
  | { action: 'rotate-credential'; clientId: string }
  | { action: 'rotate-key'; keyId: string }

interface ServiceAccountDetailProps {
  account: ServiceAccount
  onBack: () => void
  onEdit: () => void
}

export function ServiceAccountDetail({
  account,
  onBack,
  onEdit,
}: ServiceAccountDetailProps) {
  const [confirm, setConfirm] = useState<ConfirmState>(null)

  // Cross-boundary state: rotate confirmation lives in parent ConfirmDialog,
  // but the resulting "newly created" banner renders inside the sub-section.
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<ApiKeyCreated | null>(
    null,
  )
  const [newlyCreatedCredential, setNewlyCreatedCredential] =
    useState<ClientCredentialCreated | null>(null)

  const {
    data: availableRoles = [],
    isError: rolesError,
    isLoading: rolesLoading,
  } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  const {
    addOrgMutation,
    createApiKeyMutation,
    createCredentialMutation,
    removeOrgMutation,
    revokeApiKeyMutation,
    revokeCredentialMutation,
    rotateApiKeyMutation,
    rotateCredentialMutation,
    updateOrgRoleMutation,
  } = useServiceAccountMutations(account)

  // Reset cross-boundary state when the viewed account changes
  useEffect(() => {
    setNewlyCreatedKey(null)
    setNewlyCreatedCredential(null)
  }, [account.slug])

  const formatDate = (dateString?: null | string) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString(undefined, {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month: 'long',
      year: 'numeric',
    })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Service Account info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <CardTitle>{account.display_name}</CardTitle>
            <p className="mt-1 text-secondary">{account.slug}</p>
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Account
          </Button>
        </CardHeader>

        {/* Account Status */}
        <CardContent className="px-6 py-5">
          <div className="flex items-center gap-6">
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                account.is_active
                  ? 'bg-success text-success'
                  : 'bg-secondary text-secondary'
              }`}
            >
              <Power className="h-4 w-4" />
              {account.is_active ? 'Active' : 'Inactive'}
            </div>
            <div className="flex items-center gap-2 rounded bg-purple-100 px-3 py-1.5 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
              Service Account
            </div>
          </div>
        </CardContent>
      </Card>

      <OrgMembershipsCard
        account={account}
        addOrgMutation={addOrgMutation}
        availableRoles={availableRoles}
        onConfirmRemove={(orgSlug, orgName) =>
          setConfirm({ action: 'remove-org', orgName, orgSlug })
        }
        removeOrgMutation={removeOrgMutation}
        rolesError={rolesError}
        rolesLoading={rolesLoading}
        updateOrgRoleMutation={updateOrgRoleMutation}
      />

      <ClientCredentialsSection
        account={account}
        createCredentialMutation={createCredentialMutation}
        newlyCreatedCredential={newlyCreatedCredential}
        onConfirmRevoke={(clientId) =>
          setConfirm({ action: 'revoke-credential', clientId })
        }
        onConfirmRotate={(clientId) =>
          setConfirm({ action: 'rotate-credential', clientId })
        }
        onNewlyCreatedCredentialChange={setNewlyCreatedCredential}
        revokeCredentialMutation={revokeCredentialMutation}
        rotateCredentialMutation={rotateCredentialMutation}
      />

      <ApiKeysSection
        account={account}
        createApiKeyMutation={createApiKeyMutation}
        newlyCreatedKey={newlyCreatedKey}
        onConfirmRevoke={(keyId) => setConfirm({ action: 'revoke-key', keyId })}
        onConfirmRotate={(keyId) => setConfirm({ action: 'rotate-key', keyId })}
        onNewlyCreatedKeyChange={setNewlyCreatedKey}
        revokeApiKeyMutation={revokeApiKeyMutation}
        rotateApiKeyMutation={rotateApiKeyMutation}
      />

      {/* Basic Information */}
      <Card>
        <CardHeader className="space-y-0 pb-4">
          <CardTitle>Basic Information</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Tag className="h-4 w-4" />
                Slug
              </div>
              <div className="text-primary">{account.slug}</div>
            </div>

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                Display Name
              </div>
              <div className="text-primary">{account.display_name}</div>
            </div>

            {account.description && (
              <div className="col-span-2">
                <div
                  className={
                    'mb-1 flex items-center gap-2 text-sm text-secondary'
                  }
                >
                  Description
                </div>
                <div className="text-primary">{account.description}</div>
              </div>
            )}

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Calendar className="h-4 w-4" />
                Created
              </div>
              <div className="text-primary">
                {formatDate(account.created_at)}
              </div>
            </div>

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Clock className="h-4 w-4" />
                Last Authenticated
              </div>
              <div className="text-primary">
                {formatDate(account.last_authenticated)}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        confirmLabel="Revoke"
        description="Are you sure you want to revoke this API key? This action cannot be undone."
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'revoke-key') {
            revokeApiKeyMutation.mutate(confirm.keyId)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'revoke-key'}
        title="Revoke API key"
      />
      <ConfirmDialog
        confirmLabel="Rotate"
        description="Are you sure you want to rotate this API key? The old key will stop working immediately."
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'rotate-key') {
            rotateApiKeyMutation.mutate(confirm.keyId, {
              onSuccess: (data) => setNewlyCreatedKey(data),
            })
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'rotate-key'}
        title="Rotate API key"
      />
      <ConfirmDialog
        confirmLabel="Revoke"
        description="Are you sure you want to revoke this credential? This action cannot be undone."
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'revoke-credential') {
            revokeCredentialMutation.mutate(confirm.clientId)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'revoke-credential'}
        title="Revoke credential"
      />
      <ConfirmDialog
        confirmLabel="Rotate"
        description="Are you sure you want to rotate this credential? The old secret will stop working immediately."
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'rotate-credential') {
            rotateCredentialMutation.mutate(confirm.clientId, {
              onSuccess: (data) => setNewlyCreatedCredential(data),
            })
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'rotate-credential'}
        title="Rotate credential"
      />
      <ConfirmDialog
        confirmLabel="Remove"
        description={
          confirm?.action === 'remove-org'
            ? `Remove ${account.display_name} from ${confirm.orgName}?`
            : 'This action cannot be undone.'
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'remove-org') {
            removeOrgMutation.mutate(confirm.orgSlug)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'remove-org'}
        title="Remove from organization"
      />
    </div>
  )
}
