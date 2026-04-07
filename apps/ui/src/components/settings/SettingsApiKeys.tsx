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

interface SettingsApiKeysProps {
  isDarkMode: boolean
}

export function SettingsApiKeys({ isDarkMode }: SettingsApiKeysProps) {
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
      <Card
        className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
        style={{ borderWidth: '0.5px' }}
      >
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2
              className={`text-[18px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
            >
              API keys
            </h2>
            <p
              className={`mt-1 text-[12px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              Manage API keys for programmatic access
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            + Create new key
          </Button>
        </div>

        {isLoading ? (
          <p
            className={`text-[13.5px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            Loading...
          </p>
        ) : activeKeys.length === 0 ? (
          <div
            className={`rounded-lg p-8 text-center ${isDarkMode ? 'bg-gray-700/50' : 'bg-gray-50'}`}
          >
            <p
              className={`text-[13.5px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              No API keys yet. Create one to get started.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {activeKeys.map((apiKey: ApiKey) => (
              <div
                key={apiKey.key_id}
                className={`rounded-lg p-4 ${isDarkMode ? 'border-gray-600 bg-gray-700/50' : 'border-gray-200 bg-gray-50'}`}
                style={{ borderWidth: '0.5px', borderStyle: 'solid' }}
              >
                <div className="mb-3 flex items-start justify-between">
                  <div>
                    <h3
                      className={`text-[14px] font-medium ${isDarkMode ? 'text-gray-100' : 'text-gray-900'}`}
                    >
                      {apiKey.name}
                    </h3>
                    <p
                      className={`mt-1 text-[12px] ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                    >
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
                    className={`font-mono text-[12px] ${isDarkMode ? 'border-gray-600 bg-gray-800 text-gray-300' : 'bg-white'}`}
                    style={{ borderWidth: '0.5px' }}
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() =>
                      handleCopyKey(`ik_${apiKey.key_id}`, apiKey.key_id)
                    }
                    className={
                      isDarkMode
                        ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                        : ''
                    }
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
                        className={`text-[11px] ${isDarkMode ? 'border-gray-500 text-gray-300' : ''}`}
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
        className={`p-6 ${isDarkMode ? 'border-blue-800 bg-blue-900/20' : 'border-blue-200 bg-blue-50'}`}
        style={{ borderWidth: '0.5px' }}
      >
        <div className="flex gap-3">
          <span className="mt-0.5 flex-shrink-0 text-blue-600">ⓘ</span>
          <div>
            <h3
              className={`mb-1 text-[14px] font-medium ${isDarkMode ? 'text-blue-300' : 'text-blue-900'}`}
            >
              Keep your API keys secure
            </h3>
            <p
              className={`text-[12px] ${isDarkMode ? 'text-blue-400' : 'text-blue-700'}`}
            >
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
          className={isDarkMode ? 'border-gray-700 bg-gray-800' : 'bg-white'}
          style={{ borderWidth: '0.5px' }}
        >
          <DialogHeader>
            <DialogTitle className={isDarkMode ? 'text-gray-100' : ''}>
              {createdKey ? 'API key created' : 'Create new API key'}
            </DialogTitle>
          </DialogHeader>

          {createdKey ? (
            <div className="space-y-4">
              <p
                className={`text-[13.5px] ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
              >
                Copy your API key now. You won't be able to see it again.
              </p>
              <div className="flex items-center gap-2">
                <Input
                  value={createdKey.key_secret}
                  readOnly
                  className={`font-mono text-[12px] ${isDarkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : ''}`}
                  style={{ borderWidth: '0.5px' }}
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() =>
                    handleCopyKey(createdKey.key_secret, 'created')
                  }
                  className={
                    isDarkMode
                      ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                      : ''
                  }
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
                <Label className={isDarkMode ? 'text-gray-300' : ''}>
                  Key name
                </Label>
                <Input
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g. Production API Key"
                  className={`mt-2 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : ''}`}
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
                  className={
                    isDarkMode
                      ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                      : ''
                  }
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
        <DialogContent
          className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}
          style={{ borderWidth: '0.5px' }}
        >
          <DialogHeader>
            <DialogTitle className={isDarkMode ? 'text-gray-100' : ''}>
              Revoke API key
            </DialogTitle>
          </DialogHeader>
          <p
            className={`text-[13.5px] ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
          >
            Are you sure you want to revoke this API key? Any applications using
            this key will lose access immediately. This action cannot be undone.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRevokingKeyId(null)}
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
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
