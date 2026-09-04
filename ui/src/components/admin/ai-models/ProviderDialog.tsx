import { useState } from 'react'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type {
  AIProvider,
  AIProviderDriver,
  AIProviderDriverSlug,
} from '@/types'

/**
 * What the dialog collects. `api_key` is create-only; an existing
 * provider's key is changed through the credentials dialog, which
 * carries its own permission.
 */
export interface ProviderFormValues {
  api_key: null | string
  base_url: null | string
  description: null | string
  driver: AIProviderDriverSlug
  enabled: boolean
  name: string
  project_id: null | string
  region: null | string
}

interface ProviderDialogProps {
  /** Preselected driver for a "Set up" ghost row. Create mode only. */
  defaultDriver?: string
  /** Why deletion is blocked, if it is. Renders as a tooltip. */
  deleteBlockedReason?: string
  drivers: AIProviderDriver[]
  error?: unknown
  isPending: boolean
  onClose: () => void
  onDelete?: () => void
  onSubmit: (values: ProviderFormValues) => void
  open: boolean
  /** Present in edit mode; null or omitted creates a new provider. */
  provider?: AIProvider | null
}

// fallow-ignore-next-line complexity
export function ProviderDialog({
  defaultDriver,
  deleteBlockedReason,
  drivers,
  error,
  isPending,
  onClose,
  onDelete,
  onSubmit,
  open,
  provider,
}: ProviderDialogProps) {
  const editing = !!provider
  // Safe as a one-shot initializer: the caller does not mount this
  // dialog until the drivers query (and, when editing, the providers
  // query) has resolved, so these reads never see an empty list.
  const initialDriver = provider
    ? drivers.find((d) => d.slug === provider.driver)
    : (drivers.find((d) => d.slug === defaultDriver) ?? drivers[0])

  const [driverSlug, setDriverSlug] = useState<string>(
    provider?.driver ?? initialDriver?.slug ?? '',
  )
  const [name, setName] = useState(provider?.name ?? initialDriver?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(
    provider?.base_url ?? initialDriver?.default_base_url ?? '',
  )
  const [apiKey, setApiKey] = useState('')
  const [description, setDescription] = useState(provider?.description ?? '')
  const [region, setRegion] = useState(provider?.region ?? '')
  const [projectId, setProjectId] = useState(provider?.project_id ?? '')
  const [enabled, setEnabled] = useState(provider?.enabled ?? true)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const driver = drivers.find((d) => d.slug === driverSlug)
  const needsRegion = driverSlug === 'bedrock' || driverSlug === 'vertex'
  const needsProject = driverSlug === 'vertex'
  const baseUrlRequired = driver?.requires_base_url ?? false
  const canSubmit =
    name.trim().length > 0 &&
    driverSlug !== '' &&
    (!baseUrlRequired || baseUrl.trim().length > 0)

  const handleDriverChange = (slug: string) => {
    const next = drivers.find((d) => d.slug === slug)
    setDriverSlug(slug)
    setBaseUrl(next?.default_base_url ?? '')
    if (name.trim() === '' || drivers.some((d) => d.name === name)) {
      setName(next?.name ?? '')
    }
  }

  const handleSubmit = () =>
    onSubmit({
      api_key: editing ? null : apiKey.trim() || null,
      base_url: baseUrl.trim() || null,
      description: description.trim() || null,
      driver: driverSlug as AIProviderDriverSlug,
      enabled,
      name: name.trim(),
      project_id: needsProject ? projectId.trim() || null : null,
      region: needsRegion ? region.trim() || null : null,
    })

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-150">
        <DialogHeader>
          <DialogTitle>
            {editing ? `Edit ${provider.name}` : 'Add provider'}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? 'The driver cannot change once models are pointed at this provider. Credentials live in their own dialog.'
              : 'Point Imbi at a vendor API, gateway or self-hosted endpoint, then add models under it.'}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto p-6">
          {error != null && (
            <ErrorBanner
              error={error}
              title={
                editing
                  ? 'Failed to save provider'
                  : 'Failed to create provider'
              }
            />
          )}
          <FormField
            description={
              driver?.description ??
              'Determines the request shape Imbi uses when calling this provider.'
            }
            label="Driver"
            required
          >
            <Select
              disabled={editing}
              onValueChange={handleDriverChange}
              value={driverSlug}
            >
              <SelectTrigger aria-label="Driver">
                <SelectValue placeholder="Select a driver" />
              </SelectTrigger>
              <SelectContent>
                {drivers.map((d) => (
                  <SelectItem key={d.slug} value={d.slug}>
                    {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField htmlFor="ai-provider-name" label="Name" required>
            <Input
              id="ai-provider-name"
              onChange={(e) => setName(e.target.value)}
              value={name}
            />
          </FormField>
          <FormField
            description={
              baseUrlRequired
                ? undefined
                : 'Leave as-is to use the driver default.'
            }
            htmlFor="ai-provider-base-url"
            label="Base URL"
            required={baseUrlRequired}
          >
            <Input
              className="font-mono"
              id="ai-provider-base-url"
              onChange={(e) => setBaseUrl(e.target.value)}
              value={baseUrl}
            />
          </FormField>
          {needsRegion && (
            <FormField htmlFor="ai-provider-region" label="Region">
              <Input
                id="ai-provider-region"
                onChange={(e) => setRegion(e.target.value)}
                value={region}
              />
            </FormField>
          )}
          {needsProject && (
            <FormField htmlFor="ai-provider-project" label="Project ID">
              <Input
                id="ai-provider-project"
                onChange={(e) => setProjectId(e.target.value)}
                value={projectId}
              />
            </FormField>
          )}
          {!editing && (
            <FormField
              description="Optional — credentials can be set later."
              htmlFor="ai-provider-api-key"
              label="API key"
            >
              <Input
                autoComplete="new-password"
                className="font-mono"
                id="ai-provider-api-key"
                onChange={(e) => setApiKey(e.target.value)}
                type="password"
                value={apiKey}
              />
            </FormField>
          )}
          <FormField htmlFor="ai-provider-description" label="Description">
            <Textarea
              id="ai-provider-description"
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              value={description}
            />
          </FormField>
          {editing && (
            <div className="border-tertiary flex items-center justify-between rounded-md border p-3">
              <div>
                <div className="text-primary text-sm font-medium">Enabled</div>
                <p className="text-tertiary text-sm">
                  Disabling hides every model under this provider without
                  deleting them.
                </p>
              </div>
              <Switch
                aria-label="Provider enabled"
                checked={enabled}
                onCheckedChange={setEnabled}
              />
            </div>
          )}
        </div>

        <DialogFooter>
          {editing && onDelete && (
            <DeleteProviderButton
              blockedReason={deleteBlockedReason}
              onClick={() => setConfirmingDelete(true)}
            />
          )}
          <button
            className="text-secondary hover:text-primary text-sm font-medium"
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button
            className="bg-action text-action-foreground hover:bg-action-hover rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
            disabled={!canSubmit || isPending}
            onClick={handleSubmit}
            type="button"
          >
            {editing ? 'Save changes' : 'Create provider'}
          </button>
        </DialogFooter>
      </DialogContent>

      <ConfirmDialog
        confirmLabel="Delete provider"
        description="This cannot be undone. Credentials stored for this provider are removed with it."
        onCancel={() => setConfirmingDelete(false)}
        onConfirm={() => {
          setConfirmingDelete(false)
          onDelete?.()
        }}
        open={confirmingDelete}
        title={`Delete ${provider?.name ?? 'provider'}?`}
      />
    </Dialog>
  )
}

function DeleteProviderButton({
  blockedReason,
  onClick,
}: {
  blockedReason?: string
  onClick: () => void
}) {
  const button = (
    <button
      className="text-destructive mr-auto text-sm font-medium disabled:opacity-50"
      disabled={!!blockedReason}
      onClick={onClick}
      type="button"
    >
      Delete provider
    </button>
  )
  if (!blockedReason) return button
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        {/* A disabled button emits no pointer events, so the tooltip
            needs a wrapper to hang off. */}
        <TooltipTrigger asChild>
          <span className="mr-auto inline-flex">{button}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p>{blockedReason}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
