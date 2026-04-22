import { useState } from 'react'
import { ArrowLeft, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { slugify } from '@/lib/utils'
import type {
  ServiceApplication,
  ServiceApplicationCreate,
  ServiceApplicationUpdate,
} from '@/types'

interface OAuth2ApplicationFormProps {
  application: ServiceApplication | null
  onSave: (data: ServiceApplicationCreate | ServiceApplicationUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error: Error | null
}

const APP_TYPES = [
  { value: 'github_app', label: 'GitHub App' },
  { value: 'pagerduty_oauth', label: 'PagerDuty OAuth' },
  { value: 'generic_oauth2', label: 'Generic OAuth2' },
]

// Secret fields to show per app type (create mode only)
const TYPE_SECRET_FIELDS: Record<string, string[]> = {
  github_app: ['private_key', 'webhook_secret'],
  pagerduty_oauth: [],
  generic_oauth2: ['signing_secret'],
}

export function OAuth2ApplicationForm({
  application,
  onSave,
  onCancel,
  isLoading,
  error,
}: OAuth2ApplicationFormProps) {
  const isEdit = !!application

  const [slug, setSlug] = useState(application?.slug || '')
  const [name, setName] = useState(application?.name || '')
  const [description, setDescription] = useState(application?.description || '')
  const [appType, setAppType] = useState(application?.app_type || 'github_app')
  const [applicationUrl, setApplicationUrl] = useState(
    application?.application_url || '',
  )
  const [clientId, setClientId] = useState(application?.client_id || '')
  const [scopes, setScopes] = useState(application?.scopes?.join(', ') || '')
  const [status, setStatus] = useState(application?.status || 'active')
  const [validationError, setValidationError] = useState<string | null>(null)

  // Secret fields (create mode only)
  const [clientSecret, setClientSecret] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [signingSecret, setSigningSecret] = useState('')

  const extraSecretFields = TYPE_SECRET_FIELDS[appType] || []

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEdit) {
      setSlug(slugify(value))
    }
  }

  const handleSubmit = () => {
    setValidationError(null)
    if (!slug || !name || !clientId || !appType) {
      setValidationError('Slug, name, app type, and client ID are required.')
      return
    }
    if (!isEdit && !clientSecret) {
      setValidationError(
        'Client secret is required when creating an application.',
      )
      return
    }
    if (!/^[a-z][a-z0-9-]*$/.test(slug)) {
      setValidationError(
        'Slug must start with a letter and contain only lowercase letters, numbers, and hyphens.',
      )
      return
    }

    if (isEdit) {
      const data: ServiceApplicationUpdate = {
        slug,
        name,
        description: description || null,
        app_type: appType,
        application_url: applicationUrl || null,
        client_id: clientId,
        scopes: scopes
          ? scopes
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
        status,
      }
      onSave(data)
    } else {
      const data: ServiceApplicationCreate = {
        slug,
        name,
        description: description || null,
        app_type: appType,
        application_url: applicationUrl || null,
        client_id: clientId,
        client_secret: clientSecret,
        scopes: scopes
          ? scopes
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
        webhook_secret:
          extraSecretFields.includes('webhook_secret') && webhookSecret
            ? webhookSecret
            : null,
        private_key:
          extraSecretFields.includes('private_key') && privateKey
            ? privateKey
            : null,
        signing_secret:
          extraSecretFields.includes('signing_secret') && signingSecret
            ? signingSecret
            : null,
        status,
      }
      onSave(data)
    }
  }

  const inputClass = ''

  const labelClass = 'block text-sm font-medium mb-1 text-secondary'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onCancel}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <h3 className="text-base font-medium text-primary">
            {isEdit ? 'Edit Application' : 'New Application'}
          </h3>
        </div>
        <Button
          onClick={handleSubmit}
          disabled={isLoading}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          {isLoading ? 'Saving...' : isEdit ? 'Update' : 'Create'}
        </Button>
      </div>

      {/* Error display */}
      {(validationError || error) && (
        <div
          className={`flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger`}
        >
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div className="text-sm">
            {validationError ||
              (error instanceof Error ? error.message : 'An error occurred')}
          </div>
        </div>
      )}

      {/* Form */}
      <div className={`space-y-4 rounded-lg border border-border bg-card p-6`}>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Name *</label>
            <Input
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="My GitHub App"
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass}>Slug *</label>
            <Input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="my-github-app"
              disabled={isEdit}
              className={inputClass}
            />
          </div>
        </div>

        <div>
          <label className={labelClass}>Description</label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass}>Application URL</label>
          <Input
            value={applicationUrl}
            onChange={(e) => setApplicationUrl(e.target.value)}
            placeholder="https://github.com/settings/apps/my-app"
            className={inputClass}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Application Type *</label>
            <select
              value={appType}
              onChange={(e) => setAppType(e.target.value)}
              disabled={isEdit}
              className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground`}
            >
              {APP_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass}>Status</label>
            <select
              value={status}
              onChange={(e) =>
                setStatus(e.target.value as 'active' | 'inactive' | 'revoked')
              }
              className={`w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground`}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="revoked">Revoked</option>
            </select>
          </div>
        </div>

        <div>
          <label className={labelClass}>Client ID *</label>
          <Input
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="Iv1.abc123..."
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass}>Scopes</label>
          <Input
            value={scopes}
            onChange={(e) => setScopes(e.target.value)}
            placeholder="repo, read:org (comma-separated)"
            className={inputClass}
          />
        </div>

        {/* Secret fields (create mode only) */}
        {!isEdit && (
          <>
            <div className="border-t border-secondary pt-4">
              <h4 className="mb-3 text-sm font-medium text-secondary">
                Secrets
              </h4>
            </div>

            <div>
              <label className={labelClass}>Client Secret *</label>
              <Input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder="Enter client secret"
                className={inputClass}
              />
            </div>

            {extraSecretFields.includes('webhook_secret') && (
              <div>
                <label className={labelClass}>Webhook Secret</label>
                <Input
                  type="password"
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                  placeholder="Enter webhook secret"
                  className={inputClass}
                />
              </div>
            )}

            {extraSecretFields.includes('private_key') && (
              <div>
                <label className={labelClass}>Private Key (PEM)</label>
                <textarea
                  value={privateKey}
                  onChange={(e) => setPrivateKey(e.target.value)}
                  placeholder={'-----BEGIN RSA PRIVATE KEY-----\n...'}
                  rows={4}
                  className={`w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground`}
                />
              </div>
            )}

            {extraSecretFields.includes('signing_secret') && (
              <div>
                <label className={labelClass}>Signing Secret</label>
                <Input
                  type="password"
                  value={signingSecret}
                  onChange={(e) => setSigningSecret(e.target.value)}
                  placeholder="Enter signing secret"
                  className={inputClass}
                />
              </div>
            )}
          </>
        )}

        {isEdit && (
          <div className="border-t border-secondary pt-4">
            <p className="text-sm text-tertiary">
              Secrets are managed separately below via the Secrets panel.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
