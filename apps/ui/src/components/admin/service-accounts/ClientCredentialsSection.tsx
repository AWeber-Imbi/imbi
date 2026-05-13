import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { AlertCircle, Plus, RotateCw, Shield, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { listClientCredentials } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type {
  ClientCredential,
  ClientCredentialCreate,
  ClientCredentialCreated,
  ServiceAccount,
} from '@/types'

import { RevealSecretRow } from './RevealSecret'

interface ClientCredentialsSectionProps {
  account: ServiceAccount
  createCredentialMutation: UseMutationResult<
    ClientCredentialCreated,
    unknown,
    ClientCredentialCreate
  >
  newlyCreatedCredential: ClientCredentialCreated | null
  onConfirmRevoke: (clientId: string) => void
  onConfirmRotate: (clientId: string) => void
  onNewlyCreatedCredentialChange: (
    credential: ClientCredentialCreated | null,
  ) => void
  revokeCredentialMutation: UseMutationResult<unknown, unknown, string>
  rotateCredentialMutation: UseMutationResult<
    ClientCredentialCreated,
    unknown,
    string
  >
}

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

const truncateClientId = (clientId: string) => {
  if (clientId.length <= 12) return clientId
  return `${clientId.substring(0, 12)}...`
}

export function ClientCredentialsSection({
  account,
  createCredentialMutation,
  newlyCreatedCredential,
  onConfirmRevoke,
  onConfirmRotate,
  onNewlyCreatedCredentialChange,
  revokeCredentialMutation,
  rotateCredentialMutation,
}: ClientCredentialsSectionProps) {
  const [showCreateCredential, setShowCreateCredential] = useState(false)
  const [credentialName, setCredentialName] = useState('')
  const [credentialDescription, setCredentialDescription] = useState('')
  const [credentialScopes, setCredentialScopes] = useState('')
  const [credentialExpiresDays, setCredentialExpiresDays] = useState('')

  useEffect(() => {
    setShowCreateCredential(false)
    resetCredentialForm()
  }, [account.slug])

  const {
    data: credentials = [],
    error: credentialsError,
    isLoading: credentialsLoading,
  } = useQuery({
    queryFn: ({ signal }) => listClientCredentials(account.slug, signal),
    queryKey: ['clientCredentials', account.slug],
  })

  const resetCredentialForm = () => {
    setCredentialName('')
    setCredentialDescription('')
    setCredentialScopes('')
    setCredentialExpiresDays('')
  }

  const handleCreateCredential = () => {
    const scopes = credentialScopes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const expiresInDays =
      credentialExpiresDays.trim() === '' ? null : Number(credentialExpiresDays)

    if (
      expiresInDays !== null &&
      (!Number.isInteger(expiresInDays) || expiresInDays < 1)
    ) {
      toast.error('Expiration must be a positive whole number of days.')
      return
    }

    const data: ClientCredentialCreate = {
      description: credentialDescription.trim() || null,
      expires_in_days: expiresInDays,
      name: credentialName.trim(),
      scopes: scopes.length > 0 ? scopes : undefined,
    }
    createCredentialMutation.mutate(data, {
      onSuccess: (created) => {
        onNewlyCreatedCredentialChange(created)
        setShowCreateCredential(false)
        resetCredentialForm()
      },
    })
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Shield className="text-secondary size-5" />
            <CardTitle>Client Credentials</CardTitle>
          </div>
          <Button
            onClick={() => setShowCreateCredential(true)}
            size="sm"
            variant="outline"
          >
            <Plus className="mr-2 size-4" />
            Create Credential
          </Button>
        </CardHeader>
        <CardContent>
          {/* Credentials List */}
          {credentialsLoading ? (
            <div className="text-secondary py-4 text-sm">
              Loading client credentials...
            </div>
          ) : credentialsError ? (
            <div className="bg-danger text-danger flex items-center gap-2 rounded-lg p-3">
              <AlertCircle className="size-4 shrink-0" />
              <span className="text-sm">Failed to load client credentials</span>
            </div>
          ) : credentials.length === 0 ? (
            <div className="text-tertiary py-8 text-center">
              <Shield className="text-tertiary mx-auto mb-2 size-8" />
              <div>No client credentials created yet</div>
              <div className="mt-1 text-sm">
                Create a credential for OAuth2 client_credentials flow
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {credentials.map((cred: ClientCredential) => (
                <div
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    cred.revoked
                      ? 'border-input bg-secondary opacity-50'
                      : 'border-input bg-secondary'
                  }`}
                  key={cred.client_id}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-primary text-sm font-medium">
                        {cred.name}
                      </span>
                      <code className="bg-secondary text-secondary rounded px-2 py-0.5 text-xs">
                        {truncateClientId(cred.client_id)}
                      </code>
                      {cred.revoked && <Badge variant="danger">Revoked</Badge>}
                      {cred.scopes.length > 0 && cred.scopes[0] !== '*' && (
                        <span className="text-tertiary text-xs">
                          {cred.scopes.join(', ')}
                        </span>
                      )}
                    </div>
                    <div className="text-tertiary mt-1 text-xs">
                      Created {formatDate(cred.created_at)}
                      {cred.last_used &&
                        ` | Last used ${formatDate(cred.last_used)}`}
                      {cred.expires_at &&
                        ` | Expires ${formatDate(cred.expires_at)}`}
                    </div>
                  </div>
                  {!cred.revoked && (
                    <div className="flex items-center gap-1">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              aria-label={`Rotate credential ${cred.name}`}
                              className="text-info hover:bg-secondary rounded p-1.5"
                              disabled={rotateCredentialMutation.isPending}
                              onClick={() => onConfirmRotate(cred.client_id)}
                              type="button"
                            >
                              <RotateCw className="size-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Rotate credential</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              aria-label={`Revoke credential ${cred.name}`}
                              className="text-danger hover:bg-secondary rounded p-1.5"
                              disabled={revokeCredentialMutation.isPending}
                              onClick={() => onConfirmRevoke(cred.client_id)}
                              type="button"
                            >
                              <Trash2 className="size-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Revoke credential</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Newly created credential reveal modal */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) onNewlyCreatedCredentialChange(null)
        }}
        open={!!newlyCreatedCredential}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Client Credential Created</DialogTitle>
          </DialogHeader>
          {newlyCreatedCredential && (
            <div className="space-y-3 p-6">
              <p className="text-secondary text-sm">
                Copy the secret now — it will not be shown again.
              </p>
              <RevealSecretRow
                fieldLabel="Client ID"
                value={newlyCreatedCredential.client_id}
              />
              <RevealSecretRow
                fieldLabel="Client Secret"
                value={newlyCreatedCredential.client_secret}
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Create Credential modal */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) {
            setShowCreateCredential(false)
            resetCredentialForm()
          }
        }}
        open={showCreateCredential}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create Client Credential</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 p-6">
            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="credential-name"
              >
                Name <span className="text-red-500">*</span>
              </label>
              <Input
                autoFocus
                id="credential-name"
                onChange={(e) => setCredentialName(e.target.value)}
                placeholder="e.g., production-api"
                value={credentialName}
              />
            </div>
            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="credential-description"
              >
                Description
              </label>
              <Input
                id="credential-description"
                onChange={(e) => setCredentialDescription(e.target.value)}
                placeholder="What is this credential used for?"
                value={credentialDescription}
              />
            </div>
            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="credential-scopes"
              >
                Scopes{' '}
                <span className="text-tertiary text-xs">(comma-separated)</span>
              </label>
              <Input
                id="credential-scopes"
                onChange={(e) => setCredentialScopes(e.target.value)}
                placeholder="e.g., read:projects, write:projects"
                value={credentialScopes}
              />
            </div>
            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="credential-expires-days"
              >
                Expires in (days){' '}
                <span className="text-tertiary text-xs">
                  (leave empty for no expiration)
                </span>
              </label>
              <Input
                id="credential-expires-days"
                min="1"
                onChange={(e) => setCredentialExpiresDays(e.target.value)}
                placeholder="e.g., 90"
                type="number"
                value={credentialExpiresDays}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                setShowCreateCredential(false)
                resetCredentialForm()
              }}
              variant="outline"
            >
              Cancel
            </Button>
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              disabled={
                !credentialName.trim() || createCredentialMutation.isPending
              }
              onClick={handleCreateCredential}
            >
              {createCredentialMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
