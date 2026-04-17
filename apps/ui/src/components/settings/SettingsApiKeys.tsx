import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { listApiKeys, createApiKey, deleteApiKey } from '@/api/endpoints'
import type { ApiKey, ApiKeyCreated } from '@/types'
import { formatDate } from '@/lib/formatDate'

export function SettingsApiKeys() {
  const queryClient = useQueryClient()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)
  const [revokingKeyId, setRevokingKeyId] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)

  const { data: apiKeys = [], isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => listApiKeys(),
  })

  const createMutation = useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onSuccess: (data) => {
      setCreatedKey(data)
      setNewKeyName('')
      setCreateError(null)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: (error: Error) => {
      setCreateError(error.message || 'Failed to create API key')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => deleteApiKey(keyId),
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
      <Card className={'p-6'} style={{ borderWidth: '0.5px' }}>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className={'text-[18px] font-medium text-primary'}>API keys</h2>
            <p className={'mt-1 text-[12px] text-tertiary'}>
              Manage API keys for programmatic access
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            + Create new key
          </Button>
        </div>

        {isLoading ? (
          <p className={'text-[13.5px] text-tertiary'}>Loading...</p>
        ) : activeKeys.length === 0 ? (
          <div className={'bg-secondary/50 rounded-lg p-8 text-center'}>
            <p className={'text-[13.5px] text-tertiary'}>
              No API keys yet. Create one to get started.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {activeKeys.map((apiKey: ApiKey) => (
              <div
                key={apiKey.key_id}
                className={'bg-secondary/50 rounded-lg border-input p-4'}
                style={{ borderWidth: '0.5px', borderStyle: 'solid' }}
              >
                <div className="mb-3 flex items-start justify-between">
                  <div>
                    <h3 className={'text-[14px] font-medium text-primary'}>
                      {apiKey.name}
                    </h3>
                    <p className={'mt-1 text-[12px] text-tertiary'}>
                      Created {formatDate(apiKey.created_at)}
                      {apiKey.last_used &&
                        ` · Last used ${formatDate(apiKey.last_used)}`}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-600 hover:text-red-700"
                    onClick={() => setRevokingKeyId(apiKey.key_id)}
                  >
                    ✕ Revoke
                  </Button>
                </div>

                <div className="mb-3 flex items-center gap-2">
                  <Input
                    value={`ik_${apiKey.key_id}_••••••••••••`}
                    readOnly
                    className={
                      'border-input bg-card font-mono text-[12px] text-secondary'
                    }
                    style={{ borderWidth: '0.5px' }}
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() =>
                      handleCopyKey(`ik_${apiKey.key_id}`, apiKey.key_id)
                    }
                    className={''}
                    style={{ borderWidth: '0.5px' }}
                  >
                    {copiedKeyId === apiKey.key_id ? '✓' : '⎘'}
                  </Button>
                </div>

                {apiKey.scopes.length > 0 && (
                  <div className="flex gap-2">
                    {apiKey.scopes.map((scope) => (
                      <Badge
                        key={scope}
                        variant="outline"
                        className={'text-[11px]'}
                        style={{ borderWidth: '0.5px' }}
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
        className={'border-info bg-info p-6'}
        style={{ borderWidth: '0.5px' }}
      >
        <div className="flex gap-3">
          <span className="mt-0.5 flex-shrink-0 text-blue-600">ⓘ</span>
          <div>
            <h3 className={'mb-1 text-[14px] font-medium text-info'}>
              Keep your API keys secure
            </h3>
            <p className={'text-[12px] text-info'}>
              API keys grant access to your Imbi resources. Never share them or
              commit them to version control. Rotate keys regularly and revoke
              any that may have been compromised.
            </p>
          </div>
        </div>
      </Card>

      {/* Create key dialog */}
      <Dialog
        open={showCreateDialog}
        onOpenChange={(open) => {
          if (!open) {
            setShowCreateDialog(false)
            setCreatedKey(null)
            setNewKeyName('')
          }
        }}
      >
        <DialogContent
          className={'border-border bg-card'}
          style={{ borderWidth: '0.5px' }}
        >
          <DialogHeader>
            <DialogTitle>
              {createdKey ? 'API key created' : 'Create new API key'}
            </DialogTitle>
          </DialogHeader>

          {createdKey ? (
            <div className="space-y-4">
              <p className={'text-[13.5px] text-secondary'}>
                Copy your API key now. You won't be able to see it again.
              </p>
              <div className="flex items-center gap-2">
                <Input
                  value={createdKey.key_secret}
                  readOnly
                  className={'font-mono text-[12px]'}
                  style={{ borderWidth: '0.5px' }}
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() =>
                    handleCopyKey(createdKey.key_secret, 'created')
                  }
                  className={''}
                  style={{ borderWidth: '0.5px' }}
                >
                  {copiedKeyId === 'created' ? '✓' : '⎘'}
                </Button>
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
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <Label>Key name</Label>
                <Input
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g. Production API Key"
                  className={'mt-2'}
                  style={{ borderWidth: '0.5px' }}
                />
              </div>
              {createError && (
                <p className="text-[12px] text-red-600">{createError}</p>
              )}
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowCreateDialog(false)
                    setCreateError(null)
                  }}
                  className={''}
                  style={{ borderWidth: '0.5px' }}
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => createMutation.mutate(newKeyName || 'default')}
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? 'Creating...' : 'Create key'}
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Revoke confirmation dialog */}
      <Dialog
        open={!!revokingKeyId}
        onOpenChange={(open) => {
          if (!open) setRevokingKeyId(null)
        }}
      >
        <DialogContent style={{ borderWidth: '0.5px' }}>
          <DialogHeader>
            <DialogTitle>Revoke API key</DialogTitle>
          </DialogHeader>
          <p className={'text-[13.5px] text-secondary'}>
            Are you sure you want to revoke this API key? Any applications using
            this key will lose access immediately. This action cannot be undone.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRevokingKeyId(null)}
              className={''}
              style={{ borderWidth: '0.5px' }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (revokingKeyId) deleteMutation.mutate(revokingKeyId)
              }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? 'Revoking...' : 'Revoke key'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
