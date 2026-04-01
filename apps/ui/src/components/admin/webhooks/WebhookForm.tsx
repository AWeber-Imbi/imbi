import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Save,
  X,
  AlertCircle,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { IconUpload } from '@/components/ui/icon-upload'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listThirdPartyServices } from '@/api/endpoints'
import { slugify } from '@/lib/utils'
import type { AxiosError } from 'axios'
import type { Webhook, WebhookCreate, WebhookRule } from '@/types'

interface WebhookFormProps {
  webhook: Webhook | null
  onSave: (data: WebhookCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: AxiosError<{ detail?: string }> | Error | null
  defaultServiceSlug?: string
}

export function WebhookForm({
  webhook,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
  defaultServiceSlug,
}: WebhookFormProps) {
  const isEditing = !!webhook
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const [name, setName] = useState(webhook?.name || '')
  const [slug, setSlug] = useState(webhook?.slug || '')
  const [description, setDescription] = useState(webhook?.description || '')
  const [icon, setIcon] = useState(webhook?.icon || '')
  const [notificationPath, setNotificationPath] = useState(
    webhook?.notification_path || '/',
  )
  const [secret, setSecret] = useState('')
  const [tpsSlug, setTpsSlug] = useState(
    webhook?.third_party_service?.slug || defaultServiceSlug || '',
  )
  const [identifierSelector, setIdentifierSelector] = useState(
    webhook?.identifier_selector || '',
  )
  const [rules, setRules] = useState<WebhookRule[]>(webhook?.rules || [])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: services = [] } = useQuery({
    queryKey: ['third-party-services', orgSlug],
    queryFn: () => listThirdPartyServices(orgSlug),
    enabled: !!orgSlug,
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z]([a-z0-9-]*[a-z0-9])?$/.test(slug)) {
      newErrors.slug =
        'Slug must start with a letter and contain only lowercase letters, numbers, and hyphens'
    }
    if (!notificationPath.trim())
      newErrors.notification_path = 'Notification path is required'
    if (notificationPath && !notificationPath.startsWith('/')) {
      newErrors.notification_path = 'Path must start with /'
    }
    if (identifierSelector && !tpsSlug) {
      newErrors.identifier_selector =
        'Identifier selector requires a third-party service'
    }
    for (let i = 0; i < rules.length; i++) {
      if (!rules[i].filter_expression.trim()) {
        newErrors[`rule_${i}_filter`] = 'Filter expression is required'
      }
      if (!rules[i].handler.trim()) {
        newErrors[`rule_${i}_handler`] = 'Handler is required'
      }
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
      notification_path: notificationPath.trim(),
      secret: secret.trim() || null,
      third_party_service_slug: tpsSlug || null,
      identifier_selector: identifierSelector.trim() || null,
      rules: rules.map((r) => ({
        filter_expression: r.filter_expression.trim(),
        handler: r.handler.trim(),
        handler_config: r.handler_config,
      })),
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  const addRule = () => {
    setRules([
      ...rules,
      { filter_expression: '', handler: '', handler_config: {} },
    ])
  }

  const removeRule = (index: number) => {
    setRules(rules.filter((_, i) => i !== index))
  }

  const updateRuleField = (
    index: number,
    field: 'filter_expression' | 'handler',
    value: string,
  ) => {
    setRules(rules.map((r, i) => (i === index ? { ...r, [field]: value } : r)))
  }

  const updateRuleConfig = (index: number, jsonStr: string) => {
    try {
      const parsed = JSON.parse(jsonStr || '{}')
      setRules(
        rules.map((r, i) =>
          i === index ? { ...r, handler_config: parsed } : r,
        ),
      )
      setErrors((prev) => {
        const next = { ...prev }
        delete next[`rule_${index}_config`]
        return next
      })
    } catch {
      setErrors((prev) => ({
        ...prev,
        [`rule_${index}_config`]: 'Invalid JSON',
      }))
    }
  }

  const moveRule = (index: number, direction: 'up' | 'down') => {
    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= rules.length) return
    const newRules = [...rules]
    ;[newRules[index], newRules[newIndex]] = [
      newRules[newIndex],
      newRules[index],
    ]
    setRules(newRules)
  }

  const selectClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDarkMode
      ? 'bg-gray-700 border-gray-600 text-white'
      : 'bg-white border-gray-300 text-gray-900'
  }`

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2
            className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Webhook' : 'Add Webhook'}
          </h2>
          <p
            className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? 'Update webhook configuration'
              : 'Configure a new inbound webhook'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isLoading}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Webhook'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-red-700 bg-red-900/20'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className={`h-5 w-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}
              >
                Failed to save webhook
              </div>
              <div
                className={`mt-1 text-sm ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}
              >
                {(error && 'response' in error
                  ? error.response?.data?.detail
                  : undefined) ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Basic Information */}
        <div
          className={`rounded-lg border p-6 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <h3
            className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Webhook Information
          </h3>

          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., GitHub Push Events"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.name ? 'border-red-500' : ''
                  }`}
                />
                {errors.name && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., github-push-events"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.slug ? 'border-red-500' : ''
                  }`}
                />
                {errors.slug && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.slug}
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Notification Path <span className="text-red-500">*</span>
                </label>
                <Input
                  value={notificationPath}
                  onChange={(e) => setNotificationPath(e.target.value)}
                  placeholder="/webhooks/github"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.notification_path ? 'border-red-500' : ''
                  }`}
                />
                {errors.notification_path && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.notification_path}
                  </div>
                )}
              </div>

              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Secret{' '}
                  {isEditing && (
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                    >
                      (leave blank to keep current)
                    </span>
                  )}
                </label>
                <Input
                  type="password"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  placeholder={
                    isEditing ? '(unchanged)' : 'HMAC verification secret'
                  }
                  disabled={isLoading}
                  className={
                    isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                  }
                />
              </div>
            </div>

            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this webhook"
                className={`w-full resize-none rounded-lg border px-3 py-2 ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700 text-white placeholder:text-gray-400'
                    : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-500'
                }`}
              />
            </div>

            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Icon
              </label>
              <IconUpload
                value={icon}
                onChange={setIcon}
                isDarkMode={isDarkMode}
              />
            </div>
          </div>
        </div>

        {/* Third-Party Service Binding */}
        <div
          className={`rounded-lg border p-6 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <h3
            className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Third-Party Service
          </h3>
          <p
            className={`mb-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Optionally link this webhook to a third-party service for automatic
            project resolution.
          </p>

          <div className="space-y-4">
            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Third-Party Service
              </label>
              <select
                value={tpsSlug}
                onChange={(e) => {
                  setTpsSlug(e.target.value)
                  if (!e.target.value) setIdentifierSelector('')
                }}
                disabled={isLoading}
                className={selectClass}
              >
                <option value="">None</option>
                {services.map((svc) => (
                  <option key={svc.slug} value={svc.slug}>
                    {svc.name}
                  </option>
                ))}
              </select>
            </div>

            {tpsSlug && (
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Identifier Selector (JSON Path)
                </label>
                <Input
                  value={identifierSelector}
                  onChange={(e) => setIdentifierSelector(e.target.value)}
                  placeholder="e.g., $.repository.full_name"
                  disabled={isLoading}
                  className={`font-mono text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.identifier_selector ? 'border-red-500' : ''
                  }`}
                />
                {errors.identifier_selector && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.identifier_selector}
                  </div>
                )}
                <p
                  className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                >
                  JSON Path expression to extract the project identifier from
                  the webhook payload.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Rules */}
        <div
          className={`rounded-lg border p-6 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3
                className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                Rules
              </h3>
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Define filter expressions and handlers. Rules are evaluated in
                order.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addRule}
              disabled={isLoading}
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              <Plus className="mr-1 h-4 w-4" />
              Add Rule
            </Button>
          </div>

          {rules.length === 0 ? (
            <div
              className={`py-8 text-center text-sm ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              No rules defined. Click "Add Rule" to get started.
            </div>
          ) : (
            <div className="space-y-3">
              {rules.map((rule, index) => (
                <div
                  key={index}
                  className={`rounded-lg border p-4 ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700/50'
                      : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Order controls */}
                    <div className="flex flex-col gap-1 pt-1">
                      <button
                        type="button"
                        onClick={() => moveRule(index, 'up')}
                        disabled={index === 0 || isLoading}
                        className={`rounded p-1 transition-colors ${
                          index === 0
                            ? 'cursor-not-allowed opacity-30'
                            : isDarkMode
                              ? 'text-gray-400 hover:bg-gray-600'
                              : 'text-gray-500 hover:bg-gray-200'
                        }`}
                      >
                        <ArrowUp className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => moveRule(index, 'down')}
                        disabled={index === rules.length - 1 || isLoading}
                        className={`rounded p-1 transition-colors ${
                          index === rules.length - 1
                            ? 'cursor-not-allowed opacity-30'
                            : isDarkMode
                              ? 'text-gray-400 hover:bg-gray-600'
                              : 'text-gray-500 hover:bg-gray-200'
                        }`}
                      >
                        <ArrowDown className="h-3 w-3" />
                      </button>
                    </div>

                    {/* Rule number */}
                    <div
                      className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-medium ${
                        isDarkMode
                          ? 'bg-gray-600 text-gray-300'
                          : 'bg-gray-200 text-gray-600'
                      }`}
                    >
                      {index + 1}
                    </div>

                    {/* Fields */}
                    <div className="flex-1 space-y-3">
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        <div>
                          <label
                            className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                          >
                            Filter Expression (CEL){' '}
                            <span className="text-red-500">*</span>
                          </label>
                          <Input
                            value={rule.filter_expression}
                            onChange={(e) =>
                              updateRuleField(
                                index,
                                'filter_expression',
                                e.target.value,
                              )
                            }
                            placeholder='e.g., body.action == "push"'
                            disabled={isLoading}
                            className={`font-mono text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                              errors[`rule_${index}_filter`]
                                ? 'border-red-500'
                                : ''
                            }`}
                          />
                          {errors[`rule_${index}_filter`] && (
                            <div
                              className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                            >
                              <AlertCircle className="h-3 w-3" />
                              {errors[`rule_${index}_filter`]}
                            </div>
                          )}
                        </div>
                        <div>
                          <label
                            className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                          >
                            Handler <span className="text-red-500">*</span>
                          </label>
                          <Input
                            value={rule.handler}
                            onChange={(e) =>
                              updateRuleField(index, 'handler', e.target.value)
                            }
                            placeholder="e.g., imbi_gateway.handlers.sync_project"
                            disabled={isLoading}
                            className={`font-mono text-sm ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                              errors[`rule_${index}_handler`]
                                ? 'border-red-500'
                                : ''
                            }`}
                          />
                          {errors[`rule_${index}_handler`] && (
                            <div
                              className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                            >
                              <AlertCircle className="h-3 w-3" />
                              {errors[`rule_${index}_handler`]}
                            </div>
                          )}
                        </div>
                      </div>
                      <div>
                        <label
                          className={`mb-1 block text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        >
                          Handler Config (JSON)
                        </label>
                        <textarea
                          defaultValue={JSON.stringify(
                            rule.handler_config,
                            null,
                            2,
                          )}
                          onBlur={(e) =>
                            updateRuleConfig(index, e.target.value)
                          }
                          rows={6}
                          disabled={isLoading}
                          placeholder="{}"
                          className={`w-full resize-y rounded-lg border px-3 py-2 font-mono text-sm ${
                            isDarkMode
                              ? 'border-gray-600 bg-gray-700 text-white placeholder:text-gray-400'
                              : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-500'
                          } ${errors[`rule_${index}_config`] ? 'border-red-500' : ''}`}
                        />
                        {errors[`rule_${index}_config`] && (
                          <div
                            className={`mt-1 flex items-center gap-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                          >
                            <AlertCircle className="h-3 w-3" />
                            {errors[`rule_${index}_config`]}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Delete */}
                    <button
                      type="button"
                      onClick={() => removeRule(index)}
                      disabled={isLoading}
                      className={`rounded p-1.5 transition-colors ${
                        isDarkMode
                          ? 'text-red-400 hover:bg-red-900/20'
                          : 'text-red-500 hover:bg-red-50'
                      }`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </form>
    </div>
  )
}
