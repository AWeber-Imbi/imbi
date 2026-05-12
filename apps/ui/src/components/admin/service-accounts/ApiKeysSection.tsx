import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { AlertCircle, Key, Plus, RotateCw, Trash2 } from 'lucide-react'

import { listServiceAccountApiKeys } from '@/api/endpoints'
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { ApiKey, ApiKeyCreated, ServiceAccount } from '@/types'

import { RevealSecret } from './RevealSecret'

interface ApiKeysSectionProps {
  account: ServiceAccount
  createApiKeyMutation: UseMutationResult<ApiKeyCreated, unknown, string>
  newlyCreatedKey: ApiKeyCreated | null
  onConfirmRevoke: (keyId: string) => void
  onConfirmRotate: (keyId: string) => void
  onNewlyCreatedKeyChange: (key: ApiKeyCreated | null) => void
  revokeApiKeyMutation: UseMutationResult<unknown, unknown, string>
  rotateApiKeyMutation: UseMutationResult<ApiKeyCreated, unknown, string>
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

export function ApiKeysSection({
  account,
  createApiKeyMutation,
  newlyCreatedKey,
  onConfirmRevoke,
  onConfirmRotate,
  onNewlyCreatedKeyChange,
  revokeApiKeyMutation,
  rotateApiKeyMutation,
}: ApiKeysSectionProps) {
  const [newKeyName, setNewKeyName] = useState('')
  const [showCreateKey, setShowCreateKey] = useState(false)

  useEffect(() => {
    setNewKeyName('')
    setShowCreateKey(false)
  }, [account.slug])

  const {
    data: apiKeys = [],
    error: keysError,
    isLoading: keysLoading,
  } = useQuery({
    queryFn: ({ signal }) => listServiceAccountApiKeys(account.slug, signal),
    queryKey: ['serviceAccountApiKeys', account.slug],
  })

  const handleCreateKey = () => {
    if (createApiKeyMutation.isPending) return
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
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Key className="h-5 w-5 text-secondary" />
            <CardTitle>API Keys</CardTitle>
          </div>
          <Button
            onClick={() => setShowCreateKey(true)}
            size="sm"
            variant="outline"
          >
            <Plus className="mr-2 h-4 w-4" />
            Create API Key
          </Button>
        </CardHeader>
        <CardContent>
          {/* Keys List */}
          {keysLoading ? (
            <div className="py-4 text-sm text-secondary">
              Loading API keys...
            </div>
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
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    key.revoked
                      ? 'border-input bg-secondary opacity-50'
                      : 'border-input bg-secondary'
                  }`}
                  key={key.key_id}
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
                              aria-label={`Rotate API key ${key.name}`}
                              className="rounded p-1.5 text-info hover:bg-secondary"
                              disabled={rotateApiKeyMutation.isPending}
                              onClick={() => onConfirmRotate(key.key_id)}
                              type="button"
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
                              aria-label={`Revoke API key ${key.name}`}
                              className="rounded p-1.5 text-danger hover:bg-secondary"
                              disabled={revokeApiKeyMutation.isPending}
                              onClick={() => onConfirmRevoke(key.key_id)}
                              type="button"
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

      {/* Newly created key reveal modal */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) onNewlyCreatedKeyChange(null)
        }}
        open={!!newlyCreatedKey}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>API Key Created</DialogTitle>
          </DialogHeader>
          {newlyCreatedKey && (
            <div className="p-6">
              <RevealSecret
                label="Copy it now — it will not be shown again."
                onCopy={() =>
                  navigator.clipboard?.writeText(newlyCreatedKey.key_secret)
                }
                value={newlyCreatedKey.key_secret}
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Create API Key modal */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) {
            setShowCreateKey(false)
            setNewKeyName('')
          }
        }}
        open={showCreateKey}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create API Key</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 p-6">
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Key name
              </label>
              <input
                autoFocus
                className="focus:ring-action w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2"
                onChange={(e) => setNewKeyName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleCreateKey()
                  }
                }}
                placeholder="e.g., production, staging"
                type="text"
                value={newKeyName}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                setShowCreateKey(false)
                setNewKeyName('')
              }}
              variant="outline"
            >
              Cancel
            </Button>
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              disabled={createApiKeyMutation.isPending}
              onClick={handleCreateKey}
            >
              {createApiKeyMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
