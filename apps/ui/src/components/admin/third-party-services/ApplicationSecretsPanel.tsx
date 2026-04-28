import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Check,
  Copy,
  Eye,
  EyeOff,
  Save,
  Shield,
} from 'lucide-react'

import type { ApiError } from '@/api/client'
import {
  getApplicationSecrets,
  updateApplicationSecrets,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation } from '@/types'

interface ApplicationSecretsPanelProps {
  appSlug: string
  appType: string
  orgSlug: string
  serviceSlug: string
}

const TYPE_SECRET_FIELDS: Record<string, string[]> = {
  generic_oauth2: ['client_secret', 'signing_secret'],
  github_app: ['client_secret', 'private_key', 'webhook_secret'],
  pagerduty_oauth: ['client_secret'],
}

const FIELD_LABELS: Record<string, string> = {
  client_secret: 'Client Secret',
  private_key: 'Private Key (PEM)',
  signing_secret: 'Signing Secret',
  webhook_secret: 'Webhook Secret',
}

export function ApplicationSecretsPanel({
  appSlug,
  appType,
  orgSlug,
  serviceSlug,
}: ApplicationSecretsPanelProps) {
  const queryClient = useQueryClient()
  const [revealed, setRevealed] = useState(false)
  const [editing, setEditing] = useState(false)
  const [copiedField, setCopiedField] = useState<null | string>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})

  const visibleFields = TYPE_SECRET_FIELDS[appType] || ['client_secret']

  const {
    data: secrets,
    error,
    isLoading,
    refetch,
  } = useQuery({
    enabled: revealed,
    queryFn: ({ signal }) =>
      getApplicationSecrets(orgSlug, serviceSlug, appSlug, signal),
    queryKey: ['application-secrets', orgSlug, serviceSlug, appSlug],
    retry: false,
  })

  const updateMutation = useMutation({
    mutationFn: (operations: PatchOperation[]) =>
      updateApplicationSecrets(orgSlug, serviceSlug, appSlug, operations),
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
    // Only submit fields the user actually typed into. Use trim() to detect
    // blank input, but send the raw value so leading/trailing whitespace that
    // is significant (PEM blocks, signing secrets with newlines) is preserved.
    const update: Record<string, string> = {}
    for (const [field, value] of Object.entries(editValues)) {
      if (value.trim()) {
        update[field] = value
      }
    }
    if (Object.keys(update).length === 0) {
      return
    }
    // Diff against the currently loaded secrets so first-time sets (where the
    // path does not yet exist) emit `add` ops instead of `replace`, which a
    // strict RFC 6902 backend would reject.
    const operations = buildDiffPatch(
      (secrets as unknown as Record<string, unknown>) ?? {},
      update as Record<string, unknown>,
      { fields: Object.keys(update) },
    )
    if (operations.length === 0) {
      setEditing(false)
      setEditValues({})
      return
    }
    updateMutation.mutate(operations)
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
            <Button onClick={handleStartEdit} size="sm" variant="outline">
              Update Secrets
            </Button>
          )}
          {revealed ? (
            <Button onClick={handleHide} size="sm" variant="outline">
              <EyeOff className="mr-1 h-4 w-4" />
              Hide
            </Button>
          ) : (
            <Button onClick={handleReveal} size="sm" variant="outline">
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
            const value = (secrets as unknown as Record<string, null | string>)[
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
                            aria-label={`Copy ${FIELD_LABELS[field]}`}
                            className=""
                            onClick={() => handleCopy(field, value)}
                            size="sm"
                            variant="ghost"
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
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground"
                  onChange={(e) =>
                    setEditValues({ ...editValues, [field]: e.target.value })
                  }
                  placeholder="Paste new value to update"
                  rows={4}
                  value={editValues[field] || ''}
                />
              ) : (
                <Input
                  className=""
                  onChange={(e) =>
                    setEditValues({ ...editValues, [field]: e.target.value })
                  }
                  placeholder="Paste new value to update"
                  type="password"
                  value={editValues[field] || ''}
                />
              )}
            </div>
          ))}

          <div className="flex items-center gap-2 pt-2">
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              disabled={
                updateMutation.isPending ||
                Object.values(editValues).every((v) => !v.trim())
              }
              onClick={handleSave}
            >
              <Save className="mr-1 h-4 w-4" />
              {updateMutation.isPending ? 'Saving...' : 'Save Secrets'}
            </Button>
            <Button
              disabled={updateMutation.isPending}
              onClick={handleCancelEdit}
              variant="outline"
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
