import { useState } from 'react'
import { ArrowLeft, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { slugify } from '@/lib/utils'
import type { ServiceApplication, ServiceApplicationCreate, ServiceApplicationUpdate } from '@/types'

interface OAuth2ApplicationFormProps {
  application: ServiceApplication | null
  onSave: (data: ServiceApplicationCreate | ServiceApplicationUpdate) => void
  onCancel: () => void
  isDarkMode: boolean
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
  isDarkMode,
  isLoading,
  error,
}: OAuth2ApplicationFormProps) {
  const isEdit = !!application

  const [slug, setSlug] = useState(application?.slug || '')
  const [name, setName] = useState(application?.name || '')
  const [description, setDescription] = useState(application?.description || '')
  const [appType, setAppType] = useState(application?.app_type || 'github_app')
  const [applicationUrl, setApplicationUrl] = useState(application?.application_url || '')
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
      setValidationError('Client secret is required when creating an application.')
      return
    }
    if (!/^[a-z][a-z0-9-]*$/.test(slug)) {
      setValidationError('Slug must start with a letter and contain only lowercase letters, numbers, and hyphens.')
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
        scopes: scopes ? scopes.split(',').map((s) => s.trim()).filter(Boolean) : [],
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
        scopes: scopes ? scopes.split(',').map((s) => s.trim()).filter(Boolean) : [],
        webhook_secret: extraSecretFields.includes('webhook_secret') && webhookSecret ? webhookSecret : null,
        private_key: extraSecretFields.includes('private_key') && privateKey ? privateKey : null,
        signing_secret: extraSecretFields.includes('signing_secret') && signingSecret ? signingSecret : null,
        status,
      }
      onSave(data)
    }
  }

  const inputClass = isDarkMode
    ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
    : ''

  const labelClass = `block text-sm font-medium mb-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onCancel} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <h3 className={`text-lg font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEdit ? 'Edit Application' : 'New Application'}
          </h3>
        </div>
        <Button
          onClick={handleSubmit}
          disabled={isLoading}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          {isLoading ? 'Saving...' : isEdit ? 'Update' : 'Create'}
        </Button>
      </div>

      {/* Error display */}
      {(validationError || error) && (
        <div className={`flex items-center gap-3 p-4 rounded-lg border ${
          isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
        }`}>
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <div className="text-sm">
            {validationError || (error instanceof Error ? error.message : 'An error occurred')}
          </div>
        </div>
      )}

      {/* Form */}
      <div className={`p-6 rounded-lg border space-y-4 ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
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
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white'
                  : 'bg-white border-gray-300 text-gray-900'
              }`}
            >
              {APP_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass}>Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as 'active' | 'inactive' | 'revoked')}
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white'
                  : 'bg-white border-gray-300 text-gray-900'
              }`}
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
            <div className={`border-t pt-4 ${isDarkMode ? 'border-gray-600' : 'border-gray-200'}`}>
              <h4 className={`text-sm font-medium mb-3 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
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
                  className={`w-full px-3 py-2 rounded-md border text-sm font-mono ${
                    isDarkMode
                      ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
                      : 'bg-white border-gray-300 text-gray-900'
                  }`}
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
          <div className={`border-t pt-4 ${isDarkMode ? 'border-gray-600' : 'border-gray-200'}`}>
            <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              Secrets are managed separately below via the Secrets panel.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
