import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import {
  Eye,
  EyeOff,
  Copy,
  Check,
  Save,
  Shield,
  AlertCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  getApplicationSecrets,
  updateApplicationSecrets,
} from '@/api/endpoints'
import type { ServiceApplicationSecretsUpdate } from '@/types'

interface ApplicationSecretsPanelProps {
  orgSlug: string
  serviceSlug: string
  appSlug: string
  appType: string
  isDarkMode: boolean
}

const TYPE_SECRET_FIELDS: Record<string, string[]> = {
  github_app: ['client_secret', 'private_key', 'webhook_secret'],
  pagerduty_oauth: ['client_secret'],
  generic_oauth2: ['client_secret', 'signing_secret'],
}

const FIELD_LABELS: Record<string, string> = {
  client_secret: 'Client Secret',
  webhook_secret: 'Webhook Secret',
  private_key: 'Private Key (PEM)',
  signing_secret: 'Signing Secret',
}

export function ApplicationSecretsPanel({
  orgSlug,
  serviceSlug,
  appSlug,
  appType,
  isDarkMode,
}: ApplicationSecretsPanelProps) {
  const queryClient = useQueryClient()
  const [revealed, setRevealed] = useState(false)
  const [editing, setEditing] = useState(false)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})

  const visibleFields = TYPE_SECRET_FIELDS[appType] || ['client_secret']

  const {
    data: secrets,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['application-secrets', orgSlug, serviceSlug, appSlug],
    queryFn: () => getApplicationSecrets(orgSlug, serviceSlug, appSlug),
    enabled: revealed,
    retry: false,
  })

  const updateMutation = useMutation({
    mutationFn: (data: ServiceApplicationSecretsUpdate) =>
      updateApplicationSecrets(orgSlug, serviceSlug, appSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['application-secrets', orgSlug, serviceSlug, appSlug],
      })
      setEditing(false)
      setEditValues({})
      refetch()
    },
  })

  const handleReveal = () => {
    setRevealed(true)
  }

  const handleHide = () => {
    setRevealed(false)
    setEditing(false)
    setEditValues({})
  }

  const handleCopy = async (field: string, value: string) => {
    await navigator.clipboard.writeText(value)
    setCopiedField(field)
    setTimeout(() => setCopiedField(null), 2000)
  }

  const handleStartEdit = () => {
    setEditing(true)
    setEditValues({})
  }

  const handleCancelEdit = () => {
    setEditing(false)
    setEditValues({})
  }

  const handleSave = () => {
    const update: ServiceApplicationSecretsUpdate = {}
    for (const [field, value] of Object.entries(editValues)) {
      if (value.trim()) {
        ;(update as Record<string, string>)[field] = value.trim()
      }
    }
    if (Object.keys(update).length === 0) {
      return
    }
    updateMutation.mutate(update)
  }

  const is403 = error && (error as ApiError)?.response?.status === 403

  return (
    <div
      className={`rounded-lg border p-6 ${
        isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'
      }`}
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield
            className={`h-5 w-5 ${isDarkMode ? 'text-yellow-400' : 'text-yellow-600'}`}
          />
          <h3
            className={`text-lg font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Secrets
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {revealed && !editing && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleStartEdit}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              Update Secrets
            </Button>
          )}
          {revealed ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleHide}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              <EyeOff className="mr-1 h-4 w-4" />
              Hide
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={handleReveal}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              <Eye className="mr-1 h-4 w-4" />
              Reveal Secrets
            </Button>
          )}
        </div>
      </div>

      {!revealed && (
        <p
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
        >
          Secrets are hidden. Click &ldquo;Reveal Secrets&rdquo; to view or
          update them. Admin privileges required.
        </p>
      )}

      {revealed && isLoading && (
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading secrets...
        </div>
      )}

      {revealed && is403 && (
        <div
          className={`flex items-center gap-3 rounded-lg border p-4 ${
            isDarkMode
              ? 'border-yellow-700 bg-yellow-900/20 text-yellow-400'
              : 'border-yellow-200 bg-yellow-50 text-yellow-700'
          }`}
        >
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div className="text-sm">Admin access required to view secrets.</div>
        </div>
      )}

      {revealed && error && !is403 && (
        <div
          className={`flex items-center gap-3 rounded-lg border p-4 ${
            isDarkMode
              ? 'border-red-700 bg-red-900/20 text-red-400'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div className="text-sm">
            {error instanceof Error ? error.message : 'Failed to load secrets'}
          </div>
        </div>
      )}

      {revealed && secrets && !editing && (
        <div className="space-y-3">
          {visibleFields.map((field) => {
            const value = (secrets as unknown as Record<string, string | null>)[
              field
            ]
            if (value == null && field !== 'client_secret') return null
            return (
              <div key={field}>
                <div
                  className={`mb-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  {FIELD_LABELS[field]}
                </div>
                <div className="flex items-center gap-2">
                  <code
                    className={`flex-1 break-all rounded px-3 py-2 font-mono text-sm ${
                      isDarkMode
                        ? 'bg-gray-700 text-gray-200'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {field === 'private_key' ? (
                      <pre className="whitespace-pre-wrap text-xs">{value}</pre>
                    ) : (
                      value
                    )}
                  </code>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleCopy(field, value!)}
                    title="Copy to clipboard"
                    className={
                      isDarkMode ? 'text-gray-400 hover:text-gray-200' : ''
                    }
                  >
                    {copiedField === field ? (
                      <Check className="h-4 w-4 text-green-500" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {revealed && editing && (
        <div className="space-y-4">
          <p
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            Only fill in the secrets you want to change. Empty fields will be
            left unchanged.
          </p>

          {updateMutation.error && (
            <div
              className={`flex items-center gap-3 rounded-lg border p-3 ${
                isDarkMode
                  ? 'border-red-700 bg-red-900/20 text-red-400'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <div className="text-sm">
                {updateMutation.error instanceof Error
                  ? updateMutation.error.message
                  : 'Failed to update secrets'}
              </div>
            </div>
          )}

          {visibleFields.map((field) => (
            <div key={field}>
              <label
                className={`mb-1 block text-sm font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                {FIELD_LABELS[field]}
              </label>
              {field === 'private_key' ? (
                <textarea
                  value={editValues[field] || ''}
                  onChange={(e) =>
                    setEditValues({ ...editValues, [field]: e.target.value })
                  }
                  placeholder="Paste new value to update"
                  rows={4}
                  className={`w-full rounded-md border px-3 py-2 font-mono text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white placeholder-gray-400'
                      : 'border-gray-300 bg-white text-gray-900'
                  }`}
                />
              ) : (
                <Input
                  type="password"
                  value={editValues[field] || ''}
                  onChange={(e) =>
                    setEditValues({ ...editValues, [field]: e.target.value })
                  }
                  placeholder="Paste new value to update"
                  className={
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white placeholder-gray-400'
                      : ''
                  }
                />
              )}
            </div>
          ))}

          <div className="flex items-center gap-2 pt-2">
            <Button
              onClick={handleSave}
              disabled={
                updateMutation.isPending ||
                Object.values(editValues).every((v) => !v.trim())
              }
              className="bg-[#2A4DD0] text-white hover:bg-blue-700"
            >
              <Save className="mr-1 h-4 w-4" />
              {updateMutation.isPending ? 'Saving...' : 'Save Secrets'}
            </Button>
            <Button
              variant="outline"
              onClick={handleCancelEdit}
              disabled={updateMutation.isPending}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
