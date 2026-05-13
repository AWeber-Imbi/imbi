import { useState } from 'react'

import { AlertCircle } from 'lucide-react'

import { API_BASE_URL } from '@/api/client'
import { FormHeader } from '@/components/admin/form-header'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/useAuth'
import { slugify } from '@/lib/utils'
import type {
  ServiceApplication,
  ServiceApplicationCreate,
  ServiceApplicationUpdate,
} from '@/types'

const callbackUrlForSlug = (slug: string): string =>
  slug ? `${API_BASE_URL}/me/identities/${slug}/callback` : ''

interface OAuth2ApplicationFormProps {
  application: null | ServiceApplication
  error: Error | null
  isLoading: boolean
  onCancel: () => void
  onSave: (data: ServiceApplicationCreate | ServiceApplicationUpdate) => void
}

const APP_TYPES = [
  { label: 'GitHub App', value: 'github_app' },
  { label: 'PagerDuty OAuth', value: 'pagerduty_oauth' },
  { label: 'Generic OAuth2', value: 'generic_oauth2' },
]

const APP_STATUSES = ['active', 'inactive', 'revoked'] as const
type AppStatus = (typeof APP_STATUSES)[number]

function isAppStatus(value: unknown): value is AppStatus {
  return typeof value === 'string' && APP_STATUSES.includes(value as AppStatus)
}

// Secret fields to show per app type (create mode only)
const TYPE_SECRET_FIELDS: Record<string, string[]> = {
  generic_oauth2: ['signing_secret'],
  github_app: ['private_key', 'webhook_secret'],
  pagerduty_oauth: [],
}

export function OAuth2ApplicationForm({
  application,
  error,
  isLoading,
  onCancel,
  onSave,
}: OAuth2ApplicationFormProps) {
  const isEdit = !!application
  const { user } = useAuth()
  const canManageAuthProviders =
    !!user?.is_admin ||
    (user?.permissions ?? []).includes('auth_providers:write')

  const initialUsage: 'both' | 'integration' =
    application?.usage === 'both' ? 'both' : 'integration'

  const [slug, setSlug] = useState(application?.slug || '')
  const [name, setName] = useState(application?.name || '')
  const [description, setDescription] = useState(application?.description || '')
  const [appType, setAppType] = useState(application?.app_type || 'github_app')
  const [applicationUrl, setApplicationUrl] = useState(
    application?.application_url || '',
  )
  const [callbackUrl, setCallbackUrl] = useState(
    application?.callback_url || '',
  )
  // Tracks whether the user has typed into the callback URL field. Until
  // they do, we keep it in lock-step with the slug so the value matches
  // the imbi-api OAuth callback route the third party must redirect to.
  const [callbackUrlTouched, setCallbackUrlTouched] = useState(isEdit)
  const [clientId, setClientId] = useState(application?.client_id || '')
  const [scopes, setScopes] = useState(application?.scopes?.join(', ') || '')
  const [status, setStatus] = useState<AppStatus>(
    isAppStatus(application?.status) ? application.status : 'active',
  )
  const [usage, setUsage] = useState<'both' | 'integration'>(initialUsage)
  const [validationError, setValidationError] = useState<null | string>(null)

  // Secret fields (create mode only)
  const [clientSecret, setClientSecret] = useState('')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [signingSecret, setSigningSecret] = useState('')

  const extraSecretFields = TYPE_SECRET_FIELDS[appType] || []

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEdit) {
      const nextSlug = slugify(value)
      setSlug(nextSlug)
      if (!callbackUrlTouched) {
        setCallbackUrl(callbackUrlForSlug(nextSlug))
      }
    }
  }

  const handleSlugChange = (value: string) => {
    setSlug(value)
    if (!isEdit && !callbackUrlTouched) {
      setCallbackUrl(callbackUrlForSlug(value))
    }
  }

  const handleCallbackUrlChange = (value: string) => {
    setCallbackUrl(value)
    setCallbackUrlTouched(true)
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
        app_type: appType,
        application_url: applicationUrl.trim() || null,
        callback_url: callbackUrl.trim() || null,
        client_id: clientId,
        description: description || null,
        name,
        scopes: scopes
          ? scopes
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
        slug,
        status,
      }
      // Only persist a usage transition when the user has permission and
      // the value actually changed; otherwise leave the field off the
      // payload so the diff stays minimal.
      if (canManageAuthProviders && usage !== initialUsage) {
        data.usage = usage
      }
      onSave(data)
    } else {
      const data: ServiceApplicationCreate = {
        app_type: appType,
        application_url: applicationUrl.trim() || null,
        callback_url: callbackUrl.trim() || null,
        client_id: clientId,
        client_secret: clientSecret,
        description: description || null,
        name,
        private_key:
          extraSecretFields.includes('private_key') && privateKey
            ? privateKey
            : null,
        scopes: scopes
          ? scopes
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
        signing_secret:
          extraSecretFields.includes('signing_secret') && signingSecret
            ? signingSecret
            : null,
        slug,
        status,
        webhook_secret:
          extraSecretFields.includes('webhook_secret') && webhookSecret
            ? webhookSecret
            : null,
      }
      onSave(data)
    }
  }

  const inputClass = ''

  const labelClass = 'block text-sm font-medium mb-1 text-secondary'

  return (
    <div className="space-y-6">
      {/* Header */}
      <FormHeader
        createLabel="Create"
        isEditing={isEdit}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSubmit}
        title={isEdit ? 'Edit Application' : 'New Application'}
      />

      {/* Error display */}
      {(validationError || error) && (
        <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
          <AlertCircle className="size-5 shrink-0" />
          <div className="text-sm">
            {validationError ||
              (error instanceof Error ? error.message : 'An error occurred')}
          </div>
        </div>
      )}

      {/* Form */}
      <div className="border-border bg-card space-y-4 rounded-lg border p-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Name *</label>
            <Input
              className={inputClass}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="My GitHub App"
              value={name}
            />
          </div>
          <div>
            <label className={labelClass}>Slug *</label>
            <Input
              className={inputClass}
              disabled={isEdit}
              onChange={(e) => handleSlugChange(e.target.value)}
              placeholder="my-github-app"
              value={slug}
            />
          </div>
        </div>

        <div>
          <label className={labelClass}>Description</label>
          <Input
            className={inputClass}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            value={description}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className={labelClass}>Application URL</label>
            <Input
              className={inputClass}
              onChange={(e) => setApplicationUrl(e.target.value)}
              placeholder="https://github.com/settings/apps/my-app"
              value={applicationUrl}
            />
          </div>
          <div>
            <label className={labelClass}>Callback URL</label>
            <Input
              className={inputClass}
              onChange={(e) => handleCallbackUrlChange(e.target.value)}
              placeholder="https://app.example.com/auth/callback"
              value={callbackUrl}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Application Type *</label>
            <select
              className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm"
              disabled={isEdit}
              onChange={(e) => setAppType(e.target.value)}
              value={appType}
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
              className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm"
              onChange={(e) =>
                setStatus(e.target.value as 'active' | 'inactive' | 'revoked')
              }
              value={status}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="revoked">Revoked</option>
            </select>
          </div>
        </div>

        {isEdit && canManageAuthProviders && initialUsage === 'integration' && (
          <div>
            <label className={labelClass}>Usage</label>
            <div className="border-input inline-flex rounded-md border">
              <button
                className={`px-3 py-1.5 text-sm ${usage === 'integration' ? 'bg-amber-bg text-amber-text' : 'text-secondary'}`}
                onClick={() => setUsage('integration')}
                type="button"
              >
                Integration
              </button>
              <button
                className={`px-3 py-1.5 text-sm ${usage === 'both' ? 'bg-amber-bg text-amber-text' : 'text-secondary'}`}
                onClick={() => setUsage('both')}
                type="button"
              >
                Both
              </button>
            </div>
            <p className="text-tertiary mt-1 text-xs">
              Promote to "Both" to also expose this application as a login
              provider. Demoting "Both" → "Login" must be done from the Auth
              Providers screen.
            </p>
          </div>
        )}

        {isEdit && initialUsage === 'both' && (
          <div>
            <label className={labelClass}>Usage</label>
            <p className="text-secondary text-sm">
              Integration + Login. Demote from the Auth Providers screen to drop
              the login face.
            </p>
          </div>
        )}

        <div>
          <label className={labelClass}>Client ID *</label>
          <Input
            className={inputClass}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="Iv1.abc123..."
            value={clientId}
          />
        </div>

        <div>
          <label className={labelClass}>Scopes</label>
          <Input
            className={inputClass}
            onChange={(e) => setScopes(e.target.value)}
            placeholder="repo, read:org (comma-separated)"
            value={scopes}
          />
        </div>

        {/* Secret fields (create mode only) */}
        {!isEdit && (
          <>
            <div className="border-secondary border-t pt-4">
              <h4 className="text-secondary mb-3 text-sm font-medium">
                Secrets
              </h4>
            </div>

            <div>
              <label className={labelClass}>Client Secret *</label>
              <Input
                className={inputClass}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder="Enter client secret"
                type="password"
                value={clientSecret}
              />
            </div>

            {extraSecretFields.includes('webhook_secret') && (
              <div>
                <label className={labelClass}>Webhook Secret</label>
                <Input
                  className={inputClass}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                  placeholder="Enter webhook secret"
                  type="password"
                  value={webhookSecret}
                />
              </div>
            )}

            {extraSecretFields.includes('private_key') && (
              <div>
                <label className={labelClass}>Private Key (PEM)</label>
                <textarea
                  className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 font-mono text-sm"
                  onChange={(e) => setPrivateKey(e.target.value)}
                  placeholder={'-----BEGIN RSA PRIVATE KEY-----\n...'}
                  rows={4}
                  value={privateKey}
                />
              </div>
            )}

            {extraSecretFields.includes('signing_secret') && (
              <div>
                <label className={labelClass}>Signing Secret</label>
                <Input
                  className={inputClass}
                  onChange={(e) => setSigningSecret(e.target.value)}
                  placeholder="Enter signing secret"
                  type="password"
                  value={signingSecret}
                />
              </div>
            )}
          </>
        )}

        {isEdit && (
          <div className="border-secondary border-t pt-4">
            <p className="text-tertiary text-sm">
              Secrets are managed separately below via the Secrets panel.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
