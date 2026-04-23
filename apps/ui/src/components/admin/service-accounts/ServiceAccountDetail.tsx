import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2, Power, Clock, Calendar, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { getRoles } from '@/api/endpoints'
import { OrgMembershipsCard } from './OrgMembershipsCard'
import { ClientCredentialsSection } from './ClientCredentialsSection'
import { ApiKeysSection } from './ApiKeysSection'
import { useServiceAccountMutations } from './useServiceAccountMutations'
import type {
  ServiceAccount,
  ApiKeyCreated,
  ClientCredentialCreated,
} from '@/types'

interface ServiceAccountDetailProps {
  account: ServiceAccount
  onEdit: () => void
  onBack: () => void
}

type ConfirmState =
  | { action: 'revoke-key'; keyId: string }
  | { action: 'rotate-key'; keyId: string }
  | { action: 'revoke-credential'; clientId: string }
  | { action: 'rotate-credential'; clientId: string }
  | { action: 'remove-org'; orgSlug: string; orgName: string }
  | null

export function ServiceAccountDetail({
  account,
  onEdit,
  onBack,
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
    queryKey: ['roles'],
    queryFn: ({ signal }) => getRoles(signal),
  })

  const {
    addOrgMutation,
    updateOrgRoleMutation,
    removeOrgMutation,
    createApiKeyMutation,
    revokeApiKeyMutation,
    rotateApiKeyMutation,
    createCredentialMutation,
    revokeCredentialMutation,
    rotateCredentialMutation,
  } = useServiceAccountMutations(account)

  // Reset cross-boundary state when the viewed account changes
  useEffect(() => {
    setNewlyCreatedKey(null)
    setNewlyCreatedCredential(null)
  }, [account.slug])

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button variant="outline" onClick={onBack}>
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
            onClick={onEdit}
            className="bg-action text-action-foreground hover:bg-action-hover"
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
        availableRoles={availableRoles}
        rolesLoading={rolesLoading}
        rolesError={rolesError}
        addOrgMutation={addOrgMutation}
        updateOrgRoleMutation={updateOrgRoleMutation}
        removeOrgMutation={removeOrgMutation}
        onConfirmRemove={(orgSlug, orgName) =>
          setConfirm({ action: 'remove-org', orgSlug, orgName })
        }
      />

      <ClientCredentialsSection
        account={account}
        createCredentialMutation={createCredentialMutation}
        revokeCredentialMutation={revokeCredentialMutation}
        rotateCredentialMutation={rotateCredentialMutation}
        newlyCreatedCredential={newlyCreatedCredential}
        onNewlyCreatedCredentialChange={setNewlyCreatedCredential}
        onConfirmRevoke={(clientId) =>
          setConfirm({ action: 'revoke-credential', clientId })
        }
        onConfirmRotate={(clientId) =>
          setConfirm({ action: 'rotate-credential', clientId })
        }
      />

      <ApiKeysSection
        account={account}
        createApiKeyMutation={createApiKeyMutation}
        revokeApiKeyMutation={revokeApiKeyMutation}
        rotateApiKeyMutation={rotateApiKeyMutation}
        newlyCreatedKey={newlyCreatedKey}
        onNewlyCreatedKeyChange={setNewlyCreatedKey}
        onConfirmRevoke={(keyId) => setConfirm({ action: 'revoke-key', keyId })}
        onConfirmRotate={(keyId) => setConfirm({ action: 'rotate-key', keyId })}
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
        open={confirm?.action === 'revoke-key'}
        title="Revoke API key"
        description="Are you sure you want to revoke this API key? This action cannot be undone."
        confirmLabel="Revoke"
        onConfirm={() => {
          if (confirm?.action === 'revoke-key') {
            revokeApiKeyMutation.mutate(confirm.keyId)
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.action === 'rotate-key'}
        title="Rotate API key"
        description="Are you sure you want to rotate this API key? The old key will stop working immediately."
        confirmLabel="Rotate"
        onConfirm={() => {
          if (confirm?.action === 'rotate-key') {
            rotateApiKeyMutation.mutate(confirm.keyId, {
              onSuccess: (data) => setNewlyCreatedKey(data),
            })
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.action === 'revoke-credential'}
        title="Revoke credential"
        description="Are you sure you want to revoke this credential? This action cannot be undone."
        confirmLabel="Revoke"
        onConfirm={() => {
          if (confirm?.action === 'revoke-credential') {
            revokeCredentialMutation.mutate(confirm.clientId)
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.action === 'rotate-credential'}
        title="Rotate credential"
        description="Are you sure you want to rotate this credential? The old secret will stop working immediately."
        confirmLabel="Rotate"
        onConfirm={() => {
          if (confirm?.action === 'rotate-credential') {
            rotateCredentialMutation.mutate(confirm.clientId, {
              onSuccess: (data) => setNewlyCreatedCredential(data),
            })
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.action === 'remove-org'}
        title="Remove from organization"
        description={
          confirm?.action === 'remove-org'
            ? `Remove ${account.display_name} from ${confirm.orgName}?`
            : 'This action cannot be undone.'
        }
        confirmLabel="Remove"
        onConfirm={() => {
          if (confirm?.action === 'remove-org') {
            removeOrgMutation.mutate(confirm.orgSlug)
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
