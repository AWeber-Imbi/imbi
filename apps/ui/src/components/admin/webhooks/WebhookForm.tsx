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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconUpload } from '@/components/ui/icon-upload'
import { IconPicker } from '@/components/ui/icon-picker'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listThirdPartyServices } from '@/api/endpoints'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import { ApiError } from '@/api/client'
import type { Webhook, WebhookCreate, WebhookRule } from '@/types'

// Per-row client id so React preserves correct instances after reorder/remove.
// crypto.randomUUID is available in modern browsers; fall back for older envs.
function makeClientId(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID()
  }
  return `r-${Math.random().toString(36).slice(2)}-${Date.now()}`
}

type RuleDraft = WebhookRule & { _clientId: string }

interface WebhookFormProps {
  webhook: Webhook | null
  onSave: (data: WebhookCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: ApiError<{ detail?: string }> | Error | null
  defaultServiceSlug?: string
}

export function WebhookForm({
  webhook,
  onSave,
  onCancel,
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
  const handleIconChange = useIconWithCleanup(icon, setIcon)
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
  const [rules, setRules] = useState<RuleDraft[]>(() =>
    (webhook?.rules || []).map((r) => ({ ...r, _clientId: makeClientId() })),
  )
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
      {
        _clientId: makeClientId(),
        filter_expression: '',
        handler: '',
        handler_config: {},
      },
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

  const selectClass = `w-full px-3 py-2 rounded-lg border text-sm border-input bg-background text-foreground`

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-medium text-primary">
            {isEditing ? 'Edit Webhook' : 'Add Webhook'}
          </h2>
          <p className="mt-1 text-sm text-secondary">
            {isEditing
              ? 'Update webhook configuration'
              : 'Configure a new inbound webhook'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-action text-action-foreground hover:bg-action-hover"
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
      {error && <ErrorBanner title="Failed to save webhook" error={error} />}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Basic Information */}
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., GitHub Push Events"
                  disabled={isLoading}
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                />
                {errors.name && (
                  <div
                    className={
                      'mt-1 flex items-center gap-1 text-xs text-danger'
                    }
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., github-push-events"
                    disabled={isLoading}
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                  />
                  {errors.slug && (
                    <div
                      className={
                        'mt-1 flex items-center gap-1 text-xs text-danger'
                      }
                    >
                      <AlertCircle className="h-3 w-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Notification Path <span className="text-red-500">*</span>
                </label>
                <Input
                  value={notificationPath}
                  onChange={(e) => setNotificationPath(e.target.value)}
                  placeholder="/webhooks/github"
                  disabled={isLoading}
                  className={` ${
                    errors.notification_path ? 'border-red-500' : ''
                  }`}
                />
                {errors.notification_path && (
                  <div
                    className={
                      'mt-1 flex items-center gap-1 text-xs text-danger'
                    }
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.notification_path}
                  </div>
                )}
              </div>

              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Secret{' '}
                  {isEditing && (
                    <span className="text-xs text-tertiary">
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
                  className=""
                />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this webhook"
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Icon
              </label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">Pick an icon</p>
                  <IconPicker
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Third-Party Service Binding */}
        <Card>
          <CardContent className="space-y-4 pt-6">
            <p className="mb-4 text-sm text-secondary">
              Optionally link this webhook to a third-party service for
              automatic project resolution.
            </p>

            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
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
                  <label className="mb-1.5 block text-sm text-secondary">
                    Identifier Selector (JSON Path)
                  </label>
                  <Input
                    value={identifierSelector}
                    onChange={(e) => setIdentifierSelector(e.target.value)}
                    placeholder="e.g., $.repository.full_name"
                    disabled={isLoading}
                    className={`font-mono text-sm ${
                      errors.identifier_selector ? 'border-red-500' : ''
                    }`}
                  />
                  {errors.identifier_selector && (
                    <div
                      className={
                        'mt-1 flex items-center gap-1 text-xs text-danger'
                      }
                    >
                      <AlertCircle className="h-3 w-3" />
                      {errors.identifier_selector}
                    </div>
                  )}
                  <p className="mt-1 text-xs text-tertiary">
                    JSON Path expression to extract the project identifier from
                    the webhook payload.
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Rules */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-4">
            <div>
              <CardTitle>Rules</CardTitle>
              <p className="mt-1 text-sm text-secondary">
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
            >
              <Plus className="mr-1 h-4 w-4" />
              Add Rule
            </Button>
          </CardHeader>
          <CardContent>
            {rules.length === 0 ? (
              <div className="py-8 text-center text-sm text-tertiary">
                No rules defined. Click "Add Rule" to get started.
              </div>
            ) : (
              <div className="space-y-3">
                {rules.map((rule, index) => (
                  <div
                    key={rule._clientId}
                    className="bg-secondary/50 rounded-lg border border-input p-4"
                  >
                    <div className="flex items-start gap-3">
                      {/* Order controls */}
                      <div className="flex flex-col gap-1 pt-1">
                        <button
                          type="button"
                          onClick={() => moveRule(index, 'up')}
                          disabled={index === 0 || isLoading}
                          aria-label={`Move rule ${index + 1} up`}
                          title={`Move rule ${index + 1} up`}
                          className={`rounded p-1 transition-colors ${
                            index === 0
                              ? 'cursor-not-allowed opacity-30'
                              : 'text-tertiary hover:bg-secondary'
                          }`}
                        >
                          <ArrowUp className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveRule(index, 'down')}
                          disabled={index === rules.length - 1 || isLoading}
                          aria-label={`Move rule ${index + 1} down`}
                          title={`Move rule ${index + 1} down`}
                          className={`rounded p-1 transition-colors ${
                            index === rules.length - 1
                              ? 'cursor-not-allowed opacity-30'
                              : 'text-tertiary hover:bg-secondary'
                          }`}
                        >
                          <ArrowDown className="h-3 w-3" />
                        </button>
                      </div>

                      {/* Rule number */}
                      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-medium text-secondary">
                        {index + 1}
                      </div>

                      {/* Fields */}
                      <div className="flex-1 space-y-3">
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          <div>
                            <label className="mb-1 block text-xs text-secondary">
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
                              className={`font-mono text-sm ${
                                errors[`rule_${index}_filter`]
                                  ? 'border-red-500'
                                  : ''
                              }`}
                            />
                            {errors[`rule_${index}_filter`] && (
                              <div
                                className={
                                  'mt-1 flex items-center gap-1 text-xs text-danger'
                                }
                              >
                                <AlertCircle className="h-3 w-3" />
                                {errors[`rule_${index}_filter`]}
                              </div>
                            )}
                          </div>
                          <div>
                            <label className="mb-1 block text-xs text-secondary">
                              Handler <span className="text-red-500">*</span>
                            </label>
                            <Input
                              value={rule.handler}
                              onChange={(e) =>
                                updateRuleField(
                                  index,
                                  'handler',
                                  e.target.value,
                                )
                              }
                              placeholder="e.g., imbi_gateway.handlers.sync_project"
                              disabled={isLoading}
                              className={`font-mono text-sm ${
                                errors[`rule_${index}_handler`]
                                  ? 'border-red-500'
                                  : ''
                              }`}
                            />
                            {errors[`rule_${index}_handler`] && (
                              <div
                                className={
                                  'mt-1 flex items-center gap-1 text-xs text-danger'
                                }
                              >
                                <AlertCircle className="h-3 w-3" />
                                {errors[`rule_${index}_handler`]}
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs text-secondary">
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
                            className={`w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground ${
                              errors[`rule_${index}_config`]
                                ? 'border-red-500'
                                : ''
                            }`}
                          />
                          {errors[`rule_${index}_config`] && (
                            <div
                              className={
                                'mt-1 flex items-center gap-1 text-xs text-danger'
                              }
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
                        aria-label={`Delete rule ${index + 1}`}
                        title={`Delete rule ${index + 1}`}
                        className="rounded p-1.5 text-danger transition-colors hover:bg-danger"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
