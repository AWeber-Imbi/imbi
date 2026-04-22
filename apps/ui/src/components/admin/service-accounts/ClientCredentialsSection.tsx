import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus, Trash2, AlertCircle, RotateCw, Shield } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { SecretBanner } from '@/components/ui/secret-banner'
import { listClientCredentials } from '@/api/endpoints'
import type {
  ServiceAccount,
  ClientCredential,
  ClientCredentialCreate,
  ClientCredentialCreated,
} from '@/types'

interface ClientCredentialsSectionProps {
  account: ServiceAccount
  createCredentialMutation: UseMutationResult<
    ClientCredentialCreated,
    unknown,
    ClientCredentialCreate
  >
  revokeCredentialMutation: UseMutationResult<unknown, unknown, string>
  rotateCredentialMutation: UseMutationResult<
    ClientCredentialCreated,
    unknown,
    string
  >
  newlyCreatedCredential: ClientCredentialCreated | null
  onNewlyCreatedCredentialChange: (
    credential: ClientCredentialCreated | null,
  ) => void
  onConfirmRevoke: (clientId: string) => void
  onConfirmRotate: (clientId: string) => void
}

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

const truncateClientId = (clientId: string) => {
  if (clientId.length <= 12) return clientId
  return `${clientId.substring(0, 12)}...`
}

export function ClientCredentialsSection({
  account,
  createCredentialMutation,
  revokeCredentialMutation,
  rotateCredentialMutation,
  newlyCreatedCredential,
  onNewlyCreatedCredentialChange,
  onConfirmRevoke,
  onConfirmRotate,
}: ClientCredentialsSectionProps) {
  const [showCreateCredential, setShowCreateCredential] = useState(false)
  const [credentialName, setCredentialName] = useState('')
  const [credentialDescription, setCredentialDescription] = useState('')
  const [credentialScopes, setCredentialScopes] = useState('')
  const [credentialExpiresDays, setCredentialExpiresDays] = useState('')

  useEffect(() => {
    setShowCreateCredential(false)
    setCredentialName('')
    setCredentialDescription('')
    setCredentialScopes('')
    setCredentialExpiresDays('')
  }, [account.slug])

  const {
    data: credentials = [],
    isLoading: credentialsLoading,
    error: credentialsError,
  } = useQuery({
    queryKey: ['clientCredentials', account.slug],
    queryFn: () => listClientCredentials(account.slug),
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
      name: credentialName.trim(),
      description: credentialDescription.trim() || null,
      scopes: scopes.length > 0 ? scopes : undefined,
      expires_in_days: expiresInDays,
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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-secondary" />
          <CardTitle>Client Credentials</CardTitle>
        </div>
        <Button
          onClick={() => setShowCreateCredential(!showCreateCredential)}
          variant="outline"
          size="sm"
          className=""
        >
          <Plus className="mr-2 h-4 w-4" />
          Create Credential
        </Button>
      </CardHeader>
      <CardContent>
        {/* Create Credential Form */}
        {showCreateCredential && (
          <div className="mb-4 rounded-lg border border-input bg-secondary p-4">
            <div className="space-y-3">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={credentialName}
                  onChange={(e) => setCredentialName(e.target.value)}
                  placeholder="e.g., production-api"
                  className=""
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Description
                </label>
                <Input
                  value={credentialDescription}
                  onChange={(e) => setCredentialDescription(e.target.value)}
                  placeholder="What is this credential used for?"
                  className=""
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Scopes{' '}
                  <span className="text-xs text-tertiary">
                    (comma-separated)
                  </span>
                </label>
                <Input
                  value={credentialScopes}
                  onChange={(e) => setCredentialScopes(e.target.value)}
                  placeholder="e.g., read:projects, write:projects"
                  className=""
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Expires in (days){' '}
                  <span className="text-xs text-tertiary">
                    (leave empty for no expiration)
                  </span>
                </label>
                <Input
                  type="number"
                  min="1"
                  value={credentialExpiresDays}
                  onChange={(e) => setCredentialExpiresDays(e.target.value)}
                  placeholder="e.g., 90"
                  className=""
                />
              </div>
              <div className="flex items-center gap-2 pt-2">
                <Button
                  onClick={handleCreateCredential}
                  disabled={
                    !credentialName.trim() || createCredentialMutation.isPending
                  }
                  className="bg-action text-action-foreground hover:bg-action-hover"
                >
                  {createCredentialMutation.isPending
                    ? 'Creating...'
                    : 'Create'}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowCreateCredential(false)
                    resetCredentialForm()
                  }}
                  className=""
                >
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Newly Created Credential Banner */}
        {newlyCreatedCredential && (
          <SecretBanner
            title="Client Credential Created"
            description="Copy the secret now, it will not be shown again!"
            secrets={[
              {
                label: 'Client ID',
                value: newlyCreatedCredential.client_id,
                copyAriaLabel: 'Copy client ID',
              },
              {
                label: 'Client Secret',
                value: newlyCreatedCredential.client_secret,
                copyAriaLabel: 'Copy client secret',
              },
            ]}
            onDismiss={() => onNewlyCreatedCredentialChange(null)}
          />
        )}

        {/* Credentials List */}
        {credentialsLoading ? (
          <div className="py-4 text-sm text-secondary">
            Loading client credentials...
          </div>
        ) : credentialsError ? (
          <div className="flex items-center gap-2 rounded-lg bg-danger p-3 text-danger">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="text-sm">Failed to load client credentials</span>
          </div>
        ) : credentials.length === 0 ? (
          <div className="py-8 text-center text-tertiary">
            <Shield className="mx-auto mb-2 h-8 w-8 text-tertiary" />
            <div>No client credentials created yet</div>
            <div className="mt-1 text-sm">
              Create a credential for OAuth2 client_credentials flow
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {credentials.map((cred: ClientCredential) => (
              <div
                key={cred.client_id}
                className={`flex items-center justify-between rounded-lg border p-3 ${
                  cred.revoked
                    ? 'border-input bg-secondary opacity-50'
                    : 'border-input bg-secondary'
                }`}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-primary">
                      {cred.name}
                    </span>
                    <code className="rounded bg-secondary px-2 py-0.5 text-xs text-secondary">
                      {truncateClientId(cred.client_id)}
                    </code>
                    {cred.revoked && <Badge variant="danger">Revoked</Badge>}
                    {cred.scopes.length > 0 && cred.scopes[0] !== '*' && (
                      <span className="text-xs text-tertiary">
                        {cred.scopes.join(', ')}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-tertiary">
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
                            type="button"
                            aria-label={`Rotate credential ${cred.name}`}
                            onClick={() => onConfirmRotate(cred.client_id)}
                            disabled={rotateCredentialMutation.isPending}
                            className="rounded p-1.5 text-info hover:bg-secondary"
                          >
                            <RotateCw className="h-4 w-4" />
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
                            type="button"
                            aria-label={`Revoke credential ${cred.name}`}
                            onClick={() => onConfirmRevoke(cred.client_id)}
                            disabled={revokeCredentialMutation.isPending}
                            className="rounded p-1.5 text-danger hover:bg-secondary"
                          >
                            <Trash2 className="h-4 w-4" />
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
  )
}
