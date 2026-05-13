import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { createApiKey, deleteApiKey, listApiKeys } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatDate } from '@/lib/formatDate'
import type { ApiKey, ApiKeyCreated } from '@/types'

export function SettingsApiKeys() {
  const queryClient = useQueryClient()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<null | string>(null)
  const [revokingKeyId, setRevokingKeyId] = useState<null | string>(null)
  const [createError, setCreateError] = useState<null | string>(null)

  const {
    data: apiKeys = [],
    error: listError,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => listApiKeys(signal),
    queryKey: ['api-keys'],
  })

  const createMutation = useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onError: (error: Error) => {
      setCreateError(error.message || 'Failed to create API key')
    },
    onSuccess: (data) => {
      setCreatedKey(data)
      setNewKeyName('')
      setCreateError(null)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => deleteApiKey(keyId),
    onError: (error: unknown) => {
      toast.error(`Failed to revoke API key: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      setRevokingKeyId(null)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const handleCopyKey = async (text: string, keyId: string) => {
    await navigator.clipboard.writeText(text)
    setCopiedKeyId(keyId)
    setTimeout(() => setCopiedKeyId(null), 2000)
  }

  const activeKeys = apiKeys.filter((k: ApiKey) => !k.revoked)

  return (
    <div className="space-y-6">
      <Card className="p-6" style={{ borderWidth: '0.5px' }}>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-primary text-[18px] font-medium">API keys</h2>
            <p className="text-tertiary mt-1 text-[12px]">
              Manage API keys for programmatic access
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            + Create new key
          </Button>
        </div>

        {isLoading ? (
          <p className="text-tertiary text-[13.5px]">Loading...</p>
        ) : listError ? (
          <div className="bg-danger/10 text-danger rounded-lg p-4 text-[13.5px]">
            {extractApiErrorDetail(listError, 'Failed to load API keys')}
          </div>
        ) : activeKeys.length === 0 ? (
          <div className="bg-secondary/50 rounded-lg p-8 text-center">
            <p className="text-tertiary text-[13.5px]">
              No API keys yet. Create one to get started.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {activeKeys.map((apiKey: ApiKey) => (
              <div
                className="border-input bg-secondary/50 rounded-lg p-4"
                key={apiKey.key_id}
                style={{ borderStyle: 'solid', borderWidth: '0.5px' }}
              >
                <div className="mb-3 flex items-start justify-between">
                  <div>
                    <h3 className="text-primary text-[14px] font-medium">
                      {apiKey.name}
                    </h3>
                    <p className="text-tertiary mt-1 text-[12px]">
                      Created {formatDate(apiKey.created_at)}
                      {apiKey.last_used &&
                        ` · Last used ${formatDate(apiKey.last_used)}`}
                    </p>
                  </div>
                  <Button
                    className="text-red-600 hover:text-red-700"
                    onClick={() => setRevokingKeyId(apiKey.key_id)}
                    size="sm"
                    variant="ghost"
                  >
                    ✕ Revoke
                  </Button>
                </div>

                <div className="mb-3 flex items-center gap-2">
                  <Input
                    className={
                      'border-input bg-card text-secondary font-mono text-[12px]'
                    }
                    readOnly
                    style={{ borderWidth: '0.5px' }}
                    value={`ik_${apiKey.key_id}_••••••••••••`}
                  />
                  <Button
                    className=""
                    onClick={() =>
                      handleCopyKey(`ik_${apiKey.key_id}`, apiKey.key_id)
                    }
                    size="icon"
                    style={{ borderWidth: '0.5px' }}
                    variant="outline"
                  >
                    {copiedKeyId === apiKey.key_id ? '✓' : '⎘'}
                  </Button>
                </div>

                {(apiKey.scopes?.length ?? 0) > 0 && (
                  <div className="flex gap-2">
                    {apiKey.scopes?.map((scope) => (
                      <Badge
                        className="text-[11px]"
                        key={scope}
                        style={{ borderWidth: '0.5px' }}
                        variant="outline"
                      >
                        {scope}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Security info banner */}
      <Card
        className="border-info bg-info p-6"
        style={{ borderWidth: '0.5px' }}
      >
        <div className="flex gap-3">
          <span className="mt-0.5 shrink-0 text-blue-600">ⓘ</span>
          <div>
            <h3 className="text-info mb-1 text-[14px] font-medium">
              Keep your API keys secure
            </h3>
            <p className="text-info text-[12px]">
              API keys grant access to your Imbi resources. Never share them or
              commit them to version control. Rotate keys regularly and revoke
              any that may have been compromised.
            </p>
          </div>
        </div>
      </Card>

      {/* Create key dialog */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) {
            setShowCreateDialog(false)
            setCreatedKey(null)
            setNewKeyName('')
          }
        }}
        open={showCreateDialog}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {createdKey ? 'API key created' : 'Create new API key'}
            </DialogTitle>
          </DialogHeader>

          {createdKey ? (
            <>
              <div className="space-y-4 p-6">
                <p className="text-secondary text-[13.5px]">
                  Copy your API key now. You won't be able to see it again.
                </p>
                <div className="flex items-center gap-2">
                  <Input
                    className="font-mono text-[12px]"
                    readOnly
                    style={{ borderWidth: '0.5px' }}
                    value={createdKey.key_secret}
                  />
                  <Button
                    onClick={() =>
                      handleCopyKey(createdKey.key_secret, 'created')
                    }
                    size="icon"
                    style={{ borderWidth: '0.5px' }}
                    variant="outline"
                  >
                    {copiedKeyId === 'created' ? '✓' : '⎘'}
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button
                  onClick={() => {
                    setShowCreateDialog(false)
                    setCreatedKey(null)
                  }}
                >
                  Done
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <div className="space-y-4 p-6">
                <div>
                  <Label>Key name</Label>
                  <Input
                    className="mt-2"
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="e.g. Production API Key"
                    style={{ borderWidth: '0.5px' }}
                    value={newKeyName}
                  />
                </div>
                {createError && (
                  <p className="text-[12px] text-red-600">{createError}</p>
                )}
              </div>
              <DialogFooter>
                <Button
                  onClick={() => {
                    setShowCreateDialog(false)
                    setCreateError(null)
                  }}
                  style={{ borderWidth: '0.5px' }}
                  variant="outline"
                >
                  Cancel
                </Button>
                <Button
                  disabled={createMutation.isPending}
                  onClick={() => createMutation.mutate(newKeyName || 'default')}
                >
                  {createMutation.isPending ? 'Creating...' : 'Create key'}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Revoke confirmation dialog */}
      <Dialog
        onOpenChange={(open) => {
          if (!open) setRevokingKeyId(null)
        }}
        open={!!revokingKeyId}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke API key</DialogTitle>
          </DialogHeader>
          <div className="p-6">
            <p className="text-secondary text-[13.5px]">
              Are you sure you want to revoke this API key? Any applications
              using this key will lose access immediately. This action cannot be
              undone.
            </p>
          </div>
          <DialogFooter>
            <Button
              className=""
              onClick={() => setRevokingKeyId(null)}
              style={{ borderWidth: '0.5px' }}
              variant="outline"
            >
              Cancel
            </Button>
            <Button
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (revokingKeyId) deleteMutation.mutate(revokingKeyId)
              }}
              variant="destructive"
            >
              {deleteMutation.isPending ? 'Revoking...' : 'Revoke key'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
