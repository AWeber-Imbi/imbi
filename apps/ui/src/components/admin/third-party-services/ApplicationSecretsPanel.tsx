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
    <div className="border-border bg-card rounded-lg border p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="text-warning size-5" />
          <h3 className="text-primary text-base font-medium">Secrets</h3>
        </div>
        <div className="flex items-center gap-2">
          {revealed && !editing && (
            <Button onClick={handleStartEdit} size="sm" variant="outline">
              Update Secrets
            </Button>
          )}
          {revealed ? (
            <Button onClick={handleHide} size="sm" variant="outline">
              <EyeOff className="mr-1 size-4" />
              Hide
            </Button>
          ) : (
            <Button onClick={handleReveal} size="sm" variant="outline">
              <Eye className="mr-1 size-4" />
              Reveal Secrets
            </Button>
          )}
        </div>
      </div>

      {!revealed && (
        <p className="text-tertiary text-sm">
          Secrets are hidden. Click &ldquo;Reveal Secrets&rdquo; to view or
          update them. Admin privileges required.
        </p>
      )}

      {revealed && isLoading && (
        <div className="text-secondary text-sm">Loading secrets...</div>
      )}

      {revealed && is403 && (
        <div className="border-warning bg-warning text-warning flex items-center gap-3 rounded-lg border p-4">
          <AlertCircle className="size-5 shrink-0" />
          <div className="text-sm">Admin access required to view secrets.</div>
        </div>
      )}

      {revealed && error && !is403 && (
        <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
          <AlertCircle className="size-5 shrink-0" />
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
                <div className="text-secondary mb-1 text-sm">
                  {FIELD_LABELS[field]}
                </div>
                <div className="flex items-center gap-2">
                  <code className="bg-secondary text-primary flex-1 rounded px-3 py-2 font-mono text-sm break-all">
                    {field === 'private_key' ? (
                      <pre className="text-xs whitespace-pre-wrap">{value}</pre>
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
                              <Check className="size-4 text-green-500" />
                            ) : (
                              <Copy className="size-4" />
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
          <p className="text-tertiary text-sm">
            Only fill in the secrets you want to change. Empty fields will be
            left unchanged.
          </p>

          {updateMutation.error && (
            <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-3">
              <AlertCircle className="size-4 shrink-0" />
              <div className="text-sm">
                {updateMutation.error instanceof Error
                  ? updateMutation.error.message
                  : 'Failed to update secrets'}
              </div>
            </div>
          )}

          {visibleFields.map((field) => (
            <div key={field}>
              <label className="text-secondary mb-1 block text-sm font-medium">
                {FIELD_LABELS[field]}
              </label>
              {field === 'private_key' ? (
                <textarea
                  className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 font-mono text-sm"
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
              <Save className="mr-1 size-4" />
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
