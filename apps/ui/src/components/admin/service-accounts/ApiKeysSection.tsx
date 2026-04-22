import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { Plus, Trash2, AlertCircle, RotateCw, Key } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { SecretBanner } from '@/components/ui/secret-banner'
import { listServiceAccountApiKeys } from '@/api/endpoints'
import type { ServiceAccount, ApiKey, ApiKeyCreated } from '@/types'

interface ApiKeysSectionProps {
  account: ServiceAccount
  createApiKeyMutation: UseMutationResult<ApiKeyCreated, unknown, string>
  revokeApiKeyMutation: UseMutationResult<unknown, unknown, string>
  rotateApiKeyMutation: UseMutationResult<ApiKeyCreated, unknown, string>
  newlyCreatedKey: ApiKeyCreated | null
  onNewlyCreatedKeyChange: (key: ApiKeyCreated | null) => void
  onConfirmRevoke: (keyId: string) => void
  onConfirmRotate: (keyId: string) => void
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

export function ApiKeysSection({
  account,
  createApiKeyMutation,
  revokeApiKeyMutation,
  rotateApiKeyMutation,
  newlyCreatedKey,
  onNewlyCreatedKeyChange,
  onConfirmRevoke,
  onConfirmRotate,
}: ApiKeysSectionProps) {
  const [newKeyName, setNewKeyName] = useState('')
  const [showCreateKey, setShowCreateKey] = useState(false)

  useEffect(() => {
    setNewKeyName('')
    setShowCreateKey(false)
  }, [account.slug])

  const {
    data: apiKeys = [],
    isLoading: keysLoading,
    error: keysError,
  } = useQuery({
    queryKey: ['serviceAccountApiKeys', account.slug],
    queryFn: () => listServiceAccountApiKeys(account.slug),
  })

  const handleCreateKey = () => {
    const name = newKeyName.trim() || 'default'
    createApiKeyMutation.mutate(name, {
      onSuccess: (created) => {
        onNewlyCreatedKeyChange(created)
        setShowCreateKey(false)
        setNewKeyName('')
      },
    })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div className="flex items-center gap-2">
          <Key className="h-5 w-5 text-secondary" />
          <CardTitle>API Keys</CardTitle>
        </div>
        <Button
          onClick={() => setShowCreateKey(!showCreateKey)}
          variant="outline"
          size="sm"
          className=""
        >
          <Plus className="mr-2 h-4 w-4" />
          Create API Key
        </Button>
      </CardHeader>
      <CardContent>
        {/* Create Key Form */}
        {showCreateKey && (
          <div className="mb-4 rounded-lg border border-input bg-secondary p-4">
            <div className="flex items-end gap-3">
              <div className="flex-1">
                <label className="mb-1.5 block text-sm text-secondary">
                  Key Name
                </label>
                <input
                  type="text"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g., production, staging"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
                />
              </div>
              <Button
                onClick={handleCreateKey}
                disabled={createApiKeyMutation.isPending}
                className="bg-action text-action-foreground hover:bg-action-hover"
              >
                {createApiKeyMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowCreateKey(false)
                  setNewKeyName('')
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Newly Created Key Banner */}
        {newlyCreatedKey && (
          <SecretBanner
            title="API Key Created"
            description="Copy it now, it will not be shown again!"
            secrets={[
              {
                value: newlyCreatedKey.key_secret,
                copyAriaLabel: 'Copy API key',
              },
            ]}
            onDismiss={() => onNewlyCreatedKeyChange(null)}
          />
        )}

        {/* Keys List */}
        {keysLoading ? (
          <div className="py-4 text-sm text-secondary">Loading API keys...</div>
        ) : keysError ? (
          <div className="flex items-center gap-2 rounded-lg bg-danger p-3 text-danger">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="text-sm">Failed to load API keys</span>
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="py-8 text-center text-tertiary">
            <Key className="mx-auto mb-2 h-8 w-8 text-tertiary" />
            <div>No API keys created yet</div>
            <div className="mt-1 text-sm">
              Create an API key to enable programmatic access
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {apiKeys.map((key: ApiKey) => (
              <div
                key={key.key_id}
                className={`flex items-center justify-between rounded-lg border p-3 ${
                  key.revoked
                    ? 'border-input bg-secondary opacity-50'
                    : 'border-input bg-secondary'
                }`}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-primary">
                      {key.name}
                    </span>
                    <code className="rounded bg-secondary px-2 py-0.5 text-xs text-secondary">
                      {key.key_id.substring(0, 7)}...
                    </code>
                    {key.revoked && <Badge variant="danger">Revoked</Badge>}
                  </div>
                  <div className="mt-1 text-xs text-tertiary">
                    Created {formatDate(key.created_at)}
                    {key.last_used &&
                      ` | Last used ${formatDate(key.last_used)}`}
                    {key.expires_at &&
                      ` | Expires ${formatDate(key.expires_at)}`}
                  </div>
                </div>
                {!key.revoked && (
                  <div className="flex items-center gap-1">
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            aria-label={`Rotate API key ${key.name}`}
                            onClick={() => onConfirmRotate(key.key_id)}
                            disabled={rotateApiKeyMutation.isPending}
                            className="rounded p-1.5 text-info hover:bg-secondary"
                          >
                            <RotateCw className="h-4 w-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Rotate API key</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            aria-label={`Revoke API key ${key.name}`}
                            onClick={() => onConfirmRevoke(key.key_id)}
                            disabled={revokeApiKeyMutation.isPending}
                            className="rounded p-1.5 text-danger hover:bg-secondary"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Revoke API key</p>
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
