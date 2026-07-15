import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'

import { ApiError } from '@/api/client'
import { listIntegrations } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { queryKeys } from '@/lib/queryKeys'
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

// fallow-ignore-next-line complexity
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
  const [integrationSlug, setIntegrationSlug] = useState(
    (webhook?.integration?.slug as string | undefined) ||
      defaultServiceSlug ||
      '',
  )
  const [identifierSelector, setIdentifierSelector] = useState(
    webhook?.identifier_selector || '',
  )
  const [userSubjectSelector, setUserSubjectSelector] = useState(
    webhook?.user_subject_selector || '',
  )
  const [identityIntegrationSlug, setIdentityIntegrationSlug] = useState(
    webhook?.identity_integration_slug || '',
  )
  const [eventTypeSelector, setEventTypeSelector] = useState(
    webhook?.event_type_selector || '',
  )
  const [rules, setRules] = useState<RuleDraft[]>(() =>
    (webhook?.rules || []).map((r) => ({ ...r, _clientId: makeClientId() })),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: services = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
    queryKey: queryKeys.integrations(orgSlug),
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
    if (identifierSelector && !integrationSlug) {
      newErrors.identifier_selector =
        'Identifier selector requires an integration'
    }
    if (userSubjectSelector && !integrationSlug) {
      newErrors.user_subject_selector =
        'User subject selector requires an integration'
    }
    if (identityIntegrationSlug && !integrationSlug) {
      newErrors.identity_integration_slug =
        'Identity integration slug requires an integration'
    }
    if (eventTypeSelector && !integrationSlug) {
      newErrors.event_type_selector =
        'Event type selector requires an integration'
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
      event_type_selector: eventTypeSelector.trim() || null,
      icon: icon.trim() || null,
      identifier_selector: identifierSelector.trim() || null,
      identity_integration_slug: identityIntegrationSlug.trim() || null,
      integration_slug: integrationSlug || null,
      name: name.trim(),
      rules: rules.map((r) => ({
        filter_expression: r.filter_expression.trim(),
        handler: r.handler.trim(),
        handler_config: r.handler_config,
      })),
      secret: secret.trim() || null,
      user_subject_selector: userSubjectSelector.trim() || null,
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

  const handleIntegrationChange = (newIntegration: string) => {
    setIntegrationSlug(newIntegration)
    if (!newIntegration) {
      setIdentifierSelector('')
      setUserSubjectSelector('')
      setIdentityIntegrationSlug('')
      setEventTypeSelector('')
    }
    // In edit mode, auto-update the displayed slug to the computed value
    // so the user can see what will be saved if they don't override it.
    if (isEditing) {
      setSlug(computePreviewSlug(newIntegration, name))
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
              <Label className="text-secondary mb-1.5 block text-sm">
                Name <RequiredAsterisk />
              </Label>
              <Input
                className={` ${errors.name ? 'border-red-500' : ''}`}
                disabled={isLoading}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="e.g., GitHub Push Events"
                value={name}
              />
              {errors.name && (
                <div
                  className={'text-danger mt-1 flex items-center gap-1 text-xs'}
                >
                  <AlertCircle className="size-3" />
                  {errors.name}
                </div>
              )}
              {!isEditing && name && (
                <p className="text-tertiary mt-1 text-xs">
                  Slug will be auto-generated:{' '}
                  <code>{computePreviewSlug(integrationSlug, name)}</code>
                </p>
              )}
            </div>

            {/* Slug — only shown and editable when editing an existing webhook */}
            {isEditing && (
              <div>
                <Label className="text-secondary mb-1.5 block text-sm">
                  Slug{' '}
                  <span className="text-tertiary text-xs">
                    (auto-regenerated when service changes; editable)
                  </span>
                </Label>
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
                      'text-danger mt-1 flex items-center gap-1 text-xs'
                    }
                  >
                    <AlertCircle className="size-3" />
                    {errors.slug}
                  </div>
                )}
              </div>
            )}

            {/* Read-only system fields when editing */}
            {isEditing && webhook && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <Label className="text-secondary mb-1.5 block text-sm">
                    ID{' '}
                    <span className="text-tertiary text-xs">(read-only)</span>
                  </Label>
                  <div className="border-input bg-muted rounded-lg border px-3 py-2">
                    <code className="text-muted-foreground text-sm">
                      {webhook.id}
                    </code>
                  </div>
                </div>
                <div>
                  <Label className="text-secondary mb-1.5 block text-sm">
                    Notification Path{' '}
                    <span className="text-tertiary text-xs">(read-only)</span>
                  </Label>
                  <div className="border-input bg-muted rounded-lg border px-3 py-2">
                    <code className="text-muted-foreground text-sm">
                      {webhook.notification_path}
                    </code>
                  </div>
                </div>
              </div>
            )}

            <div>
              <Label className="text-secondary mb-1.5 block text-sm">
                Secret{' '}
                {isEditing && (
                  <span className="text-tertiary text-xs">
                    (leave blank to keep current)
                  </span>
                )}
              </Label>
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
              <Label className="text-secondary mb-1.5 block text-sm">
                Description
              </Label>
              <Textarea
                className="resize-none rounded-lg"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this webhook"
                rows={3}
                value={description}
              />
            </div>

            <div>
              <Label className="text-secondary mb-1.5 block text-sm">
                Icon
              </Label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="text-tertiary mb-1.5 text-xs">Pick an icon</p>
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
                  <p className="text-tertiary mb-1.5 text-xs">
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

        {/* Integration Binding */}
        <Card>
          <CardContent className="space-y-4 pt-6">
            <p className="text-secondary mb-4 text-sm">
              Optionally link this webhook to an integration for automatic
              project resolution.{' '}
              {isEditing && (
                <span className="text-tertiary text-xs">
                  Changing the integration will auto-regenerate the slug.
                </span>
              )}
            </p>

            <div className="space-y-4">
              <div>
                <Label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="webhook-integration"
                >
                  Integration
                </Label>
                {/* Radix disallows '' as a SelectItem value, so 'none' is
                    the empty sentinel and gets translated at the boundary. */}
                <Select
                  disabled={isLoading}
                  onValueChange={(v) =>
                    handleIntegrationChange(v === 'none' ? '' : v)
                  }
                  value={integrationSlug || 'none'}
                >
                  <SelectTrigger id="webhook-integration">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">None</SelectItem>
                    {services.map((svc) => (
                      <SelectItem key={svc.slug} value={svc.slug}>
                        {svc.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {integrationSlug && (
                <>
                  <div>
                    <Label className="text-secondary mb-1.5 block text-sm">
                      Identifier Selector (JSON Pointer)
                    </Label>
                    <Input
                      className={`font-mono text-sm ${
                        errors.identifier_selector ? 'border-red-500' : ''
                      }`}
                      disabled={isLoading}
                      onChange={(e) => setIdentifierSelector(e.target.value)}
                      placeholder="e.g., /repository/id"
                      value={identifierSelector}
                    />
                    {errors.identifier_selector && (
                      <div
                        className={
                          'text-danger mt-1 flex items-center gap-1 text-xs'
                        }
                      >
                        <AlertCircle className="size-3" />
                        {errors.identifier_selector}
                      </div>
                    )}
                    <p className="text-tertiary mt-1 text-xs">
                      JSON Pointer to extract the project identifier from the
                      webhook payload.
                    </p>
                  </div>

                  <div>
                    <Label className="text-secondary mb-1.5 block text-sm">
                      User Subject Selector (JSON Pointer)
                    </Label>
                    <Input
                      className={`font-mono text-sm ${
                        errors.user_subject_selector ? 'border-red-500' : ''
                      }`}
                      disabled={isLoading}
                      onChange={(e) => setUserSubjectSelector(e.target.value)}
                      placeholder="e.g., /deployment/creator/id"
                      value={userSubjectSelector}
                    />
                    {errors.user_subject_selector && (
                      <div
                        className={
                          'text-danger mt-1 flex items-center gap-1 text-xs'
                        }
                      >
                        <AlertCircle className="size-3" />
                        {errors.user_subject_selector}
                      </div>
                    )}
                    <p className="text-tertiary mt-1 text-xs">
                      JSON Pointer to the external identity subject in the
                      payload. Used to resolve the Imbi user attributed to
                      handler events.
                    </p>
                  </div>

                  <div>
                    <Label className="text-secondary mb-1.5 block text-sm">
                      Identity Integration Slug{' '}
                      <span className="text-tertiary text-xs">(optional)</span>
                    </Label>
                    <Input
                      className={`font-mono text-sm ${
                        errors.identity_integration_slug ? 'border-red-500' : ''
                      }`}
                      disabled={isLoading}
                      onChange={(e) =>
                        setIdentityIntegrationSlug(e.target.value)
                      }
                      placeholder="e.g., github"
                      value={identityIntegrationSlug}
                    />
                    {errors.identity_integration_slug && (
                      <div
                        className={
                          'text-danger mt-1 flex items-center gap-1 text-xs'
                        }
                      >
                        <AlertCircle className="size-3" />
                        {errors.identity_integration_slug}
                      </div>
                    )}
                    <p className="text-tertiary mt-1 text-xs">
                      Override which identity plugin resolves the user. Leave
                      blank to fall back to identity plugins attached to the
                      integration.
                    </p>
                  </div>

                  <div>
                    <Label className="text-secondary mb-1.5 block text-sm">
                      Event Type Selector{' '}
                      <span className="text-tertiary text-xs">(optional)</span>
                    </Label>
                    <Input
                      className={`font-mono text-sm ${
                        errors.event_type_selector ? 'border-red-500' : ''
                      }`}
                      disabled={isLoading}
                      onChange={(e) => setEventTypeSelector(e.target.value)}
                      placeholder="e.g., x-github-event or /action"
                      value={eventTypeSelector}
                    />
                    {errors.event_type_selector && (
                      <div
                        className={
                          'text-danger mt-1 flex items-center gap-1 text-xs'
                        }
                      >
                        <AlertCircle className="size-3" />
                        {errors.event_type_selector}
                      </div>
                    )}
                    <p className="text-tertiary mt-1 text-xs">
                      Resolves the activity-feed event type. Values starting
                      with <code>/</code> are JSON pointers evaluated against
                      the request body; otherwise the value is treated as an
                      HTTP header name. When the header is absent, the selector
                      itself is used as the literal label (e.g.,{' '}
                      <code>SonarQube Notification</code>).
                    </p>
                  </div>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Rules */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-4">
            <div>
              <CardTitle>Rules</CardTitle>
              <p className="text-secondary mt-1 text-sm">
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
              <Plus className="mr-1 size-4" />
              Add Rule
            </Button>
          </CardHeader>
          <CardContent>
            {rules.length === 0 ? (
              <div className="text-tertiary py-8 text-center text-sm">
                No rules defined. Click "Add Rule" to get started.
              </div>
            ) : (
              <div className="space-y-3">
                {rules.map((rule, index) => (
                  <div
                    className="border-input bg-secondary/50 rounded-lg border p-4"
                    key={rule._clientId}
                  >
                    <div className="flex items-start gap-3">
                      {/* Order controls */}
                      <div className="flex flex-col gap-1 pt-1">
                        <Button
                          aria-label={`Move rule ${index + 1} up`}
                          className="text-tertiary size-6"
                          disabled={index === 0 || isLoading}
                          onClick={() => moveRule(index, 'up')}
                          size="icon"
                          title={`Move rule ${index + 1} up`}
                          type="button"
                          variant="ghost"
                        >
                          <ArrowUp className="size-3" />
                        </Button>
                        <Button
                          aria-label={`Move rule ${index + 1} down`}
                          className="text-tertiary size-6"
                          disabled={index === rules.length - 1 || isLoading}
                          onClick={() => moveRule(index, 'down')}
                          size="icon"
                          title={`Move rule ${index + 1} down`}
                          type="button"
                          variant="ghost"
                        >
                          <ArrowDown className="size-3" />
                        </Button>
                      </div>

                      {/* Rule number */}
                      <div className="bg-secondary text-secondary flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-medium">
                        {index + 1}
                      </div>

                      {/* Fields */}
                      <div className="flex-1 space-y-3">
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          <div>
                            <Label className="text-secondary mb-1 block text-xs">
                              Filter Expression (CEL) <RequiredAsterisk />
                            </Label>
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
                                  'text-danger mt-1 flex items-center gap-1 text-xs'
                                }
                              >
                                <AlertCircle className="size-3" />
                                {errors[`rule_${index}_filter`]}
                              </div>
                            )}
                          </div>
                          <div>
                            <Label className="text-secondary mb-1 block text-xs">
                              Handler <RequiredAsterisk />
                            </Label>
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
                                  'text-danger mt-1 flex items-center gap-1 text-xs'
                                }
                              >
                                <AlertCircle className="size-3" />
                                {errors[`rule_${index}_handler`]}
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <Label className="text-secondary mb-1 block text-xs">
                            Handler Config (JSON)
                          </Label>
                          <Textarea
                            className={`resize-y rounded-lg font-mono ${
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
                                'text-danger mt-1 flex items-center gap-1 text-xs'
                              }
                            >
                              <AlertCircle className="size-3" />
                              {errors[`rule_${index}_config`]}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Delete */}
                      <Button
                        aria-label={`Delete rule ${index + 1}`}
                        className="text-danger hover:bg-danger size-8"
                        disabled={isLoading}
                        onClick={() => removeRule(index)}
                        size="icon"
                        title={`Delete rule ${index + 1}`}
                        type="button"
                        variant="ghost"
                      >
                        <Trash2 className="size-4" />
                      </Button>
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
