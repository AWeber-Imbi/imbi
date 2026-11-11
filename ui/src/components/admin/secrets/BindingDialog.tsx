import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { checkSecretLocator } from '@/api/endpoints'
import { toTitleCase } from '@/components/admin/blueprints/blueprint-schema-utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { extractApiErrorDetail } from '@/lib/apiError'

import { Chip, ChipGroup, Field, SchemaEditor, TagInput } from './controls'
import { drawable, jsonObject } from './schema'
import {
  changedFields,
  CREDENTIAL_CLASSES,
  DELIVERY_MODES,
  duration,
  type SecretBinding,
  type SecretProvider,
  type SecretProviderType,
  titleList,
} from './types'

const PREFIX = 'secret://'

const CLASS_HELP: Record<string, string> = {
  dynamic:
    'Dynamic mints a short-lived credential per request, for example through workload identity.',
  rotated: 'Rotated reads a stored value that the provider rotates.',
  static: 'Static reads a stored value.',
}

interface BindingDialogProps {
  /** The hosts of the github_app providers. */
  appHosts: string[]
  /** The github_app bindings that can sign with this key. */
  consumers: KeyConsumer[]
  error?: unknown
  isPending: boolean
  onClose: () => void
  onSubmit: (body: Record<string, unknown>) => void
  orgSlug: string
  /** The binding to edit. The dialog then sends only the changed fields. */
  original?: SecretBinding
  providers: SecretProvider[]
  providerTypes: SecretProviderType[]
}

// A Select item value cannot be empty: this one clears the host.
const NO_HOST = '__none__'

interface KeyConsumer {
  appId: string
  host: string
  label: string
  value: string
}

interface KeyUsage {
  app_id: string
  consumers?: string[]
  host: string
}

/** The create or edit dialog for a binding. */
// fallow-ignore-next-line complexity
export function BindingDialog({
  appHosts,
  consumers,
  error,
  isPending,
  onClose,
  onSubmit,
  orgSlug,
  original,
  providers,
  providerTypes,
}: BindingDialogProps) {
  const usage = original?.provider_key_usage as KeyUsage | null | undefined
  const [form, setForm] = useState(() => ({
    allowed_delivery_modes: original?.allowed_delivery_modes ?? [],
    allowed_delivery_targets: original?.allowed_delivery_targets ?? [],
    allowed_fields: original?.allowed_fields ?? [],
    app_id: usage?.app_id ?? '',
    // Drop saved ids of deleted bindings: no checkbox can clear them.
    consumers: (usage?.consumers ?? []).filter((id) =>
      consumers.some((c) => c.value === id),
    ),
    credential_class: original?.credential_class ?? 'static',
    description: original?.description ?? '',
    host: usage?.host ?? '',
    locator: original ? JSON.stringify(original.locator, null, 2) : '{}',
    max_ttl_seconds: String(original?.max_ttl_seconds ?? 900),
    path: '',
    provider_id: original?.provider_id ?? '',
  }))
  type Form = typeof form
  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const provider = providers.find((p) => p.id === form.provider_id)
  const typeLabel = (type: string) =>
    providerTypes.find((t) => t.type === type)?.label ?? toTitleCase(type)
  const providerType = providerTypes.find((t) => t.type === provider?.type)
  const classes = providerType?.credential_classes ?? CREDENTIAL_CLASSES
  const schema = drawable(providerType?.locator_schema)
  const parsed = jsonObject(form.locator)
  // A new provider can allow other classes: keep the class valid.
  const setProvider = (id: string) => {
    const type = providers.find((p) => p.id === id)?.type
    const allowed = providerTypes.find(
      (t) => t.type === type,
    )?.credential_classes
    setForm((prev) => ({
      ...prev,
      credential_class:
        allowed?.length && !allowed.includes(prev.credential_class)
          ? allowed[0]
          : prev.credential_class,
      provider_id: id,
    }))
  }
  const reference = original?.reference ?? PREFIX + form.path.trim()
  const locator = useLocatorCheck(
    orgSlug,
    form.provider_id,
    form.credential_class,
    form.locator,
  )

  // The main id of the locator, such as an AWS secret_id, for the summary.
  const where = schema?.required
    ?.map((k) => parsed?.[k])
    .find((v): v is string => typeof v === 'string' && !!v)

  // A key binding can hold a provider key, such as a GitHub App key.
  const keyClass = form.credential_class !== 'dynamic'
  const keyUsed = !!(
    form.host.trim() ||
    form.app_id.trim() ||
    form.consumers.length
  )
  // A ticked consumer sets the host and App id: the broker accepts the
  // key only for the host and App id of each consumer.
  const pinned = form.consumers.length > 0
  const toggleConsumer = (c: KeyConsumer, on: boolean) =>
    setForm((prev) => ({
      ...prev,
      app_id: on ? c.appId : prev.app_id,
      consumers: on
        ? [...prev.consumers, c.value]
        : prev.consumers.filter((v) => v !== c.value),
      host: on ? c.host : prev.host,
    }))
  const hosts = [...new Set([...appHosts, form.host].filter(Boolean))]
  const ttl = Number(form.max_ttl_seconds)
  const ready =
    (!!original || (/^[a-z0-9]/.test(form.path) && !!form.provider_id)) &&
    form.allowed_delivery_modes.length > 0 &&
    ttl > 0 &&
    (!keyClass || !keyUsed || (!!form.host.trim() && !!form.app_id.trim())) &&
    !locator.error &&
    !locator.checking

  const submit = () => {
    const body: Record<string, unknown> = {
      allowed_delivery_modes: form.allowed_delivery_modes,
      allowed_delivery_targets: form.allowed_delivery_targets,
      allowed_fields: form.allowed_fields,
      credential_class: form.credential_class,
      description: form.description.trim(),
      locator: JSON.parse(form.locator) as unknown,
      max_ttl_seconds: ttl,
    }
    if (keyClass) {
      body.provider_key_usage = keyUsed
        ? {
            app_id: form.app_id.trim(),
            consumers: form.consumers,
            host: form.host.trim(),
          }
        : null
    }
    if (!original) {
      for (const key of Object.keys(body)) {
        const value = body[key]
        if (
          value === '' ||
          value === null ||
          (Array.isArray(value) && !value.length)
        )
          delete body[key]
      }
      return onSubmit({ ...body, provider_id: form.provider_id, reference })
    }
    const changed = changedFields(body, original)
    if (!Object.keys(changed).length) return onClose()
    onSubmit(changed)
  }

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent className="max-w-180">
        <DialogHeader>
          <DialogTitle>{original ? 'Edit binding' : 'New binding'}</DialogTitle>
          <DialogDescription>
            Points a reference at where a secret lives in a provider. The
            binding never stores the secret itself.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-5 overflow-y-auto p-6">
          {error != null && (
            <ErrorBanner error={error} title="Failed to save the binding" />
          )}
          <Field
            help="Scope, then path, in lower case. Agents and grants use this name."
            htmlFor="binding-reference"
            label="Reference"
            required
          >
            {original ? (
              <p className="font-mono text-sm" id="binding-reference">
                {original.reference}
              </p>
            ) : (
              <div className="border-input flex h-9 overflow-hidden rounded-md border">
                <span className="border-tertiary bg-tertiary text-secondary flex items-center border-r px-2.5 font-mono text-xs">
                  {PREFIX}
                </span>
                <input
                  className="min-w-0 flex-1 bg-transparent px-2.5 font-mono text-sm outline-none"
                  id="binding-reference"
                  onChange={(e) =>
                    set('path', e.target.value.replace(PREFIX, ''))
                  }
                  placeholder="dev/app_db"
                  value={form.path}
                />
              </div>
            )}
          </Field>
          <div className="space-y-1.5">
            <div className="grid grid-cols-2 gap-4">
              <Field htmlFor="binding-provider" label="Provider" required>
                {original ? (
                  <p className="text-sm" id="binding-provider">
                    {provider?.name ?? original.provider_id}
                  </p>
                ) : (
                  <Select onValueChange={setProvider} value={form.provider_id}>
                    <SelectTrigger aria-label="Provider" id="binding-provider">
                      <SelectValue placeholder="Select a provider" />
                    </SelectTrigger>
                    <SelectContent>
                      {providers.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name}{' '}
                          <span className="text-secondary">
                            · {typeLabel(p.type)}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </Field>
              <Field label="Credential class" required>
                <SegmentedControl
                  ariaLabel="Credential class"
                  className="flex w-full"
                  onValueChange={(value) => set('credential_class', value)}
                  value={form.credential_class}
                >
                  {CREDENTIAL_CLASSES.map((c) => (
                    <SegmentedControlItem
                      className="flex-1 justify-center py-1.5 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!classes.includes(c)}
                      key={c}
                      value={c}
                    >
                      {toTitleCase(c)}
                    </SegmentedControlItem>
                  ))}
                </SegmentedControl>
              </Field>
            </div>
            <p className="text-secondary text-xs">
              {CLASS_HELP[form.credential_class]}
            </p>
          </div>
          <SchemaEditor
            error={locator.error}
            hint={
              provider
                ? `where the secret lives in ${typeLabel(provider.type)}`
                : 'where the secret lives in the provider'
            }
            id="binding-locator"
            label="Locator"
            onChange={(text) => set('locator', text)}
            schema={providerType?.locator_schema}
            text={form.locator}
          />
          <Field
            help="JSON keys an agent may ask for on their own. Leave empty to deliver only the whole value."
            htmlFor="binding-fields"
            label="Allowed fields"
          >
            <TagInput
              id="binding-fields"
              onChange={(values) => set('allowed_fields', values)}
              placeholder="Add a field, press Enter"
              values={form.allowed_fields}
            />
          </Field>
          <ChipGroup
            hint="the most a grant can allow"
            label="Allowed delivery modes"
          >
            {DELIVERY_MODES.map((mode) => (
              <Chip
                checked={form.allowed_delivery_modes.includes(mode)}
                key={mode}
                label={titleList([mode])}
                onChange={(on) =>
                  set(
                    'allowed_delivery_modes',
                    on
                      ? [...form.allowed_delivery_modes, mode]
                      : form.allowed_delivery_modes.filter((m) => m !== mode),
                  )
                }
              />
            ))}
          </ChipGroup>
          <div className="grid grid-cols-[1fr_auto] gap-4">
            <Field
              help="For example GH_TOKEN. Empty allows any safe target."
              htmlFor="binding-targets"
              label="Allowed delivery targets"
            >
              <TagInput
                id="binding-targets"
                onChange={(values) => set('allowed_delivery_targets', values)}
                placeholder="Add a target, press Enter"
                values={form.allowed_delivery_targets}
              />
            </Field>
            <Field htmlFor="binding-ttl" label="Maximum TTL">
              <span className="flex items-center gap-2">
                <Input
                  className="w-24"
                  id="binding-ttl"
                  min={1}
                  onChange={(e) => set('max_ttl_seconds', e.target.value)}
                  type="number"
                  value={form.max_ttl_seconds}
                />
                <span className="text-tertiary text-sm">
                  sec{ttl > 0 && ` · ${duration(ttl)}`}
                </span>
              </span>
            </Field>
          </div>
          <Field htmlFor="binding-description" label="Description" optional>
            <Input
              id="binding-description"
              onChange={(e) => set('description', e.target.value)}
              placeholder="What this secret is for"
              value={form.description}
            />
          </Field>
          {keyClass && (
            <fieldset className="border-tertiary space-y-3 rounded-lg border p-3.5">
              <legend className="px-1 text-sm font-medium">
                Provider key{' '}
                <span className="text-secondary font-normal">
                  only for a key that signs, such as a GitHub App private key
                </span>
              </legend>
              <div className="grid grid-cols-2 gap-4">
                <Field
                  help="github.com, <tenant>.ghe.com, or a GHES host"
                  htmlFor="binding-key-host"
                  label="Provider key host"
                  required={keyUsed}
                >
                  {appHosts.length ? (
                    <Select
                      disabled={pinned}
                      onValueChange={(value) =>
                        set('host', value === NO_HOST ? '' : value)
                      }
                      value={form.host}
                    >
                      <SelectTrigger
                        aria-label="Provider key host"
                        id="binding-key-host"
                      >
                        <SelectValue placeholder="Select a host" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_HOST}>None</SelectItem>
                        {hosts.map((h) => (
                          <SelectItem key={h} value={h}>
                            {h}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id="binding-key-host"
                      onChange={(e) => set('host', e.target.value)}
                      value={form.host}
                    />
                  )}
                </Field>
                <Field
                  htmlFor="binding-key-app"
                  label="Provider key App id"
                  required={keyUsed}
                >
                  <Input
                    id="binding-key-app"
                    onChange={(e) => set('app_id', e.target.value)}
                    readOnly={pinned}
                    value={form.app_id}
                  />
                </Field>
              </div>
              {consumers.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">
                    Consumers{' '}
                    <span className="text-secondary font-normal">
                      the github_app bindings that can sign with the key
                    </span>
                  </p>
                  {consumers.map((c) => {
                    const checked = form.consumers.includes(c.value)
                    return (
                      <label
                        className="flex items-center gap-2 font-mono text-xs"
                        key={c.value}
                      >
                        <Checkbox
                          aria-label={c.label}
                          checked={checked}
                          // Another App or host cannot share the key.
                          disabled={
                            !checked &&
                            pinned &&
                            (c.host !== form.host || c.appId !== form.app_id)
                          }
                          onCheckedChange={(on) =>
                            toggleConsumer(c, on === true)
                          }
                        />
                        {c.label}
                      </label>
                    )
                  })}
                </div>
              )}
            </fieldset>
          )}
        </div>
        <DialogFooter className="items-center gap-4">
          <p className="text-secondary mr-auto min-w-0 text-xs">
            {provider && reference !== PREFIX && (
              <>
                <span className="text-primary font-mono">{reference}</span>{' '}
                {form.credential_class === 'dynamic'
                  ? `mints a fresh ${typeLabel(provider.type)} credential per request.`
                  : `reads ${where ? `${where} ` : ''}from ${provider.name}, ${
                      form.allowed_fields.length
                        ? `fields ${form.allowed_fields.join(', ')}`
                        : 'the whole value'
                    }.`}
              </>
            )}
          </p>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button disabled={isPending || !ready} onClick={submit}>
            {original ? 'Save' : 'Create binding'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Check the locator with the rules of a save, a moment after the admin
 * stops typing. Return the reason it is not valid, and whether a check
 * is still to come.
 */
// fallow-ignore-next-line complexity
function useLocatorCheck(
  orgSlug: string,
  providerId: string,
  credentialClass: string,
  text: string,
) {
  let parsed: null | Record<string, unknown> = null
  let parseError: string | undefined
  try {
    const value: unknown = JSON.parse(text || 'null')
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      parsed = value as Record<string, unknown>
    } else {
      parseError = 'The locator must be a JSON object'
    }
  } catch {
    parseError = 'The locator is not valid JSON'
  }
  const request =
    parsed && providerId
      ? JSON.stringify({
          credential_class: credentialClass,
          locator: parsed,
          provider_id: providerId,
        })
      : ''
  const debounced = useDebouncedValue(request, 400)
  const check = useQuery({
    enabled: !!debounced,
    // A query cannot hold undefined, and the 204 has no body.
    queryFn: async () => {
      await checkSecretLocator(orgSlug, JSON.parse(debounced))
      return true
    },
    queryKey: ['secret-locator-check', orgSlug, debounced],
    retry: false,
    staleTime: Infinity,
  })
  if (parseError) return { checking: false, error: parseError }
  if (!request) return { checking: false, error: undefined }
  return {
    checking: request !== debounced || check.isFetching,
    error: check.error ? extractApiErrorDetail(check.error) : undefined,
  }
}
