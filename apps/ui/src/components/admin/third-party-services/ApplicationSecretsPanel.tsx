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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface ApplicationSecretsPanelProps {
  orgSlug: string
  serviceSlug: string
  appSlug: string
  appType: string
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
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-warning" />
          <h3 className="text-base font-medium text-primary">Secrets</h3>
        </div>
        <div className="flex items-center gap-2">
          {revealed && !editing && (
            <Button variant="outline" size="sm" onClick={handleStartEdit}>
              Update Secrets
            </Button>
          )}
          {revealed ? (
            <Button variant="outline" size="sm" onClick={handleHide}>
              <EyeOff className="mr-1 h-4 w-4" />
              Hide
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={handleReveal}>
              <Eye className="mr-1 h-4 w-4" />
              Reveal Secrets
            </Button>
          )}
        </div>
      </div>

      {!revealed && (
        <p className="text-sm text-tertiary">
          Secrets are hidden. Click &ldquo;Reveal Secrets&rdquo; to view or
          update them. Admin privileges required.
        </p>
      )}

      {revealed && isLoading && (
        <div className="text-sm text-secondary">Loading secrets...</div>
      )}

      {revealed && is403 && (
        <div className="flex items-center gap-3 rounded-lg border border-warning bg-warning p-4 text-warning">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div className="text-sm">Admin access required to view secrets.</div>
        </div>
      )}

      {revealed && error && !is403 && (
        <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
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
                <div className="mb-1 text-sm text-secondary">
                  {FIELD_LABELS[field]}
                </div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-secondary px-3 py-2 font-mono text-sm text-primary">
                    {field === 'private_key' ? (
                      <pre className="whitespace-pre-wrap text-xs">{value}</pre>
                    ) : (
                      value
                    )}
                  </code>
                  {value != null && (
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Copy ${FIELD_LABELS[field]}`}
                            onClick={() => handleCopy(field, value)}
                            className=""
                          >
                            {copiedField === field ? (
                              <Check className="h-4 w-4 text-green-500" />
                            ) : (
                              <Copy className="h-4 w-4" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Copy to clipboard</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {revealed && editing && (
        <div className="space-y-4">
          <p className="text-sm text-tertiary">
            Only fill in the secrets you want to change. Empty fields will be
            left unchanged.
          </p>

          {updateMutation.error && (
            <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-3 text-danger">
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
              <label className="mb-1 block text-sm font-medium text-secondary">
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
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground"
                />
              ) : (
                <Input
                  type="password"
                  value={editValues[field] || ''}
                  onChange={(e) =>
                    setEditValues({ ...editValues, [field]: e.target.value })
                  }
                  placeholder="Paste new value to update"
                  className=""
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
              className="bg-action text-action-foreground hover:bg-action-hover"
            >
              <Save className="mr-1 h-4 w-4" />
              {updateMutation.isPending ? 'Saving...' : 'Save Secrets'}
            </Button>
            <Button
              variant="outline"
              onClick={handleCancelEdit}
              disabled={updateMutation.isPending}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
