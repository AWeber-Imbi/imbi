import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'

import { ApiError } from '@/api/client'
import { listThirdPartyServices } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type { Webhook, WebhookCreate, WebhookRule } from '@/types'

/** WebhookCreate plus an optional slug included only when editing. */
export type WebhookSaveData = WebhookCreate & { slug?: string }

type RuleDraft = WebhookRule & { _clientId: string }

interface WebhookFormProps {
  defaultServiceSlug?: string
  error?: ApiError<{ detail?: string }> | Error | null
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: WebhookSaveData) => void
  webhook: null | Webhook
}

export function WebhookForm({
  defaultServiceSlug,
  error,
  isLoading = false,
  onCancel,
  onSave,
  webhook,
}: WebhookFormProps) {
  const isEditing = !!webhook
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const [name, setName] = useState(webhook?.name || '')
  const [slug, setSlug] = useState(webhook?.slug || '')
  const [description, setDescription] = useState(webhook?.description || '')
  const [icon, setIcon] = useState(webhook?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [secret, setSecret] = useState('')
  const [tpsSlug, setTpsSlug] = useState(
    (webhook?.third_party_service?.slug as string | undefined) ||
      defaultServiceSlug ||
      '',
  )
  const [identifierSelector, setIdentifierSelector] = useState(
    webhook?.identifier_selector || '',
  )
  const [rules, setRules] = useState<RuleDraft[]>(() =>
    (webhook?.rules || []).map((r) => ({ ...r, _clientId: makeClientId() })),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: services = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listThirdPartyServices(orgSlug, signal),
    queryKey: ['third-party-services', orgSlug],
  })

  // Compute what the auto-generated slug would look like for a given
  // service+name pair (mirrors _compute_webhook_slug in the API).
  const computePreviewSlug = (svc: string, n: string) => {
    const namePart = slugify(n)
    if (svc) return `${svc}-${namePart}`.slice(0, 64).replace(/-+$/, '')
    return namePart.slice(0, 64).replace(/-+$/, '')
  }

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (isEditing) {
      if (!slug.trim()) newErrors.slug = 'Slug is required'
      if (slug && !/^[a-z]([a-z0-9-]*[a-z0-9])?$/.test(slug)) {
        newErrors.slug =
          'Slug must start with a letter and contain only lowercase letters, numbers, and hyphens'
      }
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

  const handleSave = () => {
    if (!validate()) return

    const payload: WebhookSaveData = {
      description: description.trim() || null,
      icon: icon.trim() || null,
      identifier_selector: identifierSelector.trim() || null,
      name: name.trim(),
      rules: rules.map((r) => ({
        filter_expression: r.filter_expression.trim(),
        handler: r.handler.trim(),
        handler_config: r.handler_config,
      })),
      secret: secret.trim() || null,
      third_party_service_slug: tpsSlug || null,
      // Include slug only when editing so the PATCH can update it.
      ...(isEditing ? { slug: slug.trim() } : {}),
    }
    onSave(payload)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSave()
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      // Preview only — actual slug is computed by the API on save.
      // When editing, the slug field is directly managed by the user.
    }
  }

  const handleServiceChange = (newTps: string) => {
    setTpsSlug(newTps)
    if (!newTps) setIdentifierSelector('')
    // In edit mode, auto-update the displayed slug to the computed value
    // so the user can see what will be saved if they don't override it.
    if (isEditing) {
      setSlug(computePreviewSlug(newTps, name))
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

  const moveRule = (index: number, direction: 'down' | 'up') => {
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
      <FormHeader
        createLabel="Create Webhook"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? 'Update webhook configuration'
            : 'Configure a new inbound webhook'
        }
        title={isEditing ? 'Edit Webhook' : 'Add Webhook'}
      />

      {/* API Error */}
      {error && <ErrorBanner error={error} title="Failed to save webhook" />}

      {/* Form */}
      <form className="space-y-6" onSubmit={handleSubmit}>
        {/* Basic Information */}
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Name <span className="text-red-500">*</span>
              </label>
              <Input
                className={` ${errors.name ? 'border-red-500' : ''}`}
                disabled={isLoading}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="e.g., GitHub Push Events"
                value={name}
              />
              {errors.name && (
                <div
                  className={'mt-1 flex items-center gap-1 text-xs text-danger'}
                >
                  <AlertCircle className="h-3 w-3" />
                  {errors.name}
                </div>
              )}
              {!isEditing && name && (
                <p className="mt-1 text-xs text-tertiary">
                  Slug will be auto-generated:{' '}
                  <code>{computePreviewSlug(tpsSlug, name)}</code>
                </p>
              )}
            </div>

            {/* Slug — only shown and editable when editing an existing webhook */}
            {isEditing && (
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Slug{' '}
                  <span className="text-xs text-tertiary">
                    (auto-regenerated when service changes; editable)
                  </span>
                </label>
                <Input
                  className={` ${errors.slug ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., github-push-events"
                  value={slug}
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

            {/* Read-only system fields when editing */}
            {isEditing && webhook && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    ID{' '}
                    <span className="text-xs text-tertiary">(read-only)</span>
                  </label>
                  <div className="rounded-lg border border-input bg-muted px-3 py-2">
                    <code className="text-sm text-muted-foreground">
                      {webhook.id}
                    </code>
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    Notification Path{' '}
                    <span className="text-xs text-tertiary">(read-only)</span>
                  </label>
                  <div className="rounded-lg border border-input bg-muted px-3 py-2">
                    <code className="text-sm text-muted-foreground">
                      {webhook.notification_path}
                    </code>
                  </div>
                </div>
              </div>
            )}

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
                className=""
                disabled={isLoading}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={
                  isEditing ? '(unchanged)' : 'HMAC verification secret'
                }
                type="password"
                value={secret}
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Description
              </label>
              <textarea
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this webhook"
                rows={3}
                value={description}
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
                    onChange={handleIconChange}
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                  />
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    onChange={handleIconChange}
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
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
              automatic project resolution.{' '}
              {isEditing && (
                <span className="text-xs text-tertiary">
                  Changing the service will auto-regenerate the slug.
                </span>
              )}
            </p>

            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Third-Party Service
                </label>
                <select
                  className={selectClass}
                  disabled={isLoading}
                  onChange={(e) => handleServiceChange(e.target.value)}
                  value={tpsSlug}
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
                    className={`font-mono text-sm ${
                      errors.identifier_selector ? 'border-red-500' : ''
                    }`}
                    disabled={isLoading}
                    onChange={(e) => setIdentifierSelector(e.target.value)}
                    placeholder="e.g., $.repository.full_name"
                    value={identifierSelector}
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
              disabled={isLoading}
              onClick={addRule}
              size="sm"
              type="button"
              variant="outline"
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
                    className="bg-secondary/50 rounded-lg border border-input p-4"
                    key={rule._clientId}
                  >
                    <div className="flex items-start gap-3">
                      {/* Order controls */}
                      <div className="flex flex-col gap-1 pt-1">
                        <button
                          aria-label={`Move rule ${index + 1} up`}
                          className={`rounded p-1 transition-colors ${
                            index === 0
                              ? 'cursor-not-allowed opacity-30'
                              : 'text-tertiary hover:bg-secondary'
                          }`}
                          disabled={index === 0 || isLoading}
                          onClick={() => moveRule(index, 'up')}
                          title={`Move rule ${index + 1} up`}
                          type="button"
                        >
                          <ArrowUp className="h-3 w-3" />
                        </button>
                        <button
                          aria-label={`Move rule ${index + 1} down`}
                          className={`rounded p-1 transition-colors ${
                            index === rules.length - 1
                              ? 'cursor-not-allowed opacity-30'
                              : 'text-tertiary hover:bg-secondary'
                          }`}
                          disabled={index === rules.length - 1 || isLoading}
                          onClick={() => moveRule(index, 'down')}
                          title={`Move rule ${index + 1} down`}
                          type="button"
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
                              className={`font-mono text-sm ${
                                errors[`rule_${index}_filter`]
                                  ? 'border-red-500'
                                  : ''
                              }`}
                              disabled={isLoading}
                              onChange={(e) =>
                                updateRuleField(
                                  index,
                                  'filter_expression',
                                  e.target.value,
                                )
                              }
                              placeholder='e.g., body.action == "push"'
                              value={rule.filter_expression}
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
                              className={`font-mono text-sm ${
                                errors[`rule_${index}_handler`]
                                  ? 'border-red-500'
                                  : ''
                              }`}
                              disabled={isLoading}
                              onChange={(e) =>
                                updateRuleField(
                                  index,
                                  'handler',
                                  e.target.value,
                                )
                              }
                              placeholder="e.g., imbi_gateway.handlers.sync_project"
                              value={rule.handler}
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
                            className={`w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground ${
                              errors[`rule_${index}_config`]
                                ? 'border-red-500'
                                : ''
                            }`}
                            defaultValue={JSON.stringify(
                              rule.handler_config,
                              null,
                              2,
                            )}
                            disabled={isLoading}
                            onBlur={(e) =>
                              updateRuleConfig(index, e.target.value)
                            }
                            placeholder="{}"
                            rows={6}
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
                        aria-label={`Delete rule ${index + 1}`}
                        className="rounded p-1.5 text-danger transition-colors hover:bg-danger"
                        disabled={isLoading}
                        onClick={() => removeRule(index)}
                        title={`Delete rule ${index + 1}`}
                        type="button"
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

// Per-row client id so React preserves correct instances after reorder/remove.
function makeClientId(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID()
  }
  return `r-${Math.random().toString(36).slice(2)}-${Date.now()}`
}
