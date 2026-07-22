import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Package,
} from 'lucide-react'

import {
  createIntegration,
  listProjectTypes,
  replaceCapabilityAssignments,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { capabilityMeta } from '@/lib/capabilities'
import { queryKeys } from '@/lib/queryKeys'
import { cn, slugify } from '@/lib/utils'
import type {
  CapabilityKind,
  Integration,
  IntegrationCreate,
  PluginCapability,
  PluginOption,
  PluginPackage,
} from '@/types'

import { CapabilityRow } from './CapabilityRow'
import { FieldDescription } from './FieldDescription'

interface CapabilityState {
  assigned: string[]
  enabled: boolean
  options: Record<string, unknown>
}

interface IntegrationWizardProps {
  onCancel: () => void
  onCreated: (integration: Integration) => void
  plugins: PluginPackage[]
}

const STEP_LABELS = ['Plugin', 'Connection', 'Capabilities', 'Review']

// fallow-ignore-next-line complexity
export function IntegrationWizard({
  onCancel,
  onCreated,
  plugins,
}: IntegrationWizardProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const queryClient = useQueryClient()

  const [step, setStep] = useState(1)
  const [pluginSlug, setPluginSlug] = useState<null | string>(
    plugins.length === 1 ? plugins[0].slug : null,
  )
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugEdited, setSlugEdited] = useState(false)
  const [options, setOptions] = useState<Record<string, unknown>>({})
  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [caps, setCaps] = useState<Record<string, CapabilityState>>({})
  const [showOptionalCreds, setShowOptionalCreds] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const plugin = useMemo(
    () => plugins.find((p) => p.slug === pluginSlug) ?? null,
    [plugins, pluginSlug],
  )

  const { data: projectTypes = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug!, signal),
    queryKey: orgSlug ? queryKeys.projectTypes(orgSlug) : ['projectTypes'],
  })

  const selectPlugin = (p: PluginPackage) => {
    setPluginSlug(p.slug)
    const opts: Record<string, unknown> = {}
    for (const opt of p.options) opts[opt.name] = optionDefault(opt)
    setOptions(opts)
    setCredentials({})
    setCaps(initCapabilities(p.capabilities))
    setErrors({})
  }

  const createMutation = useMutation({
    // fallow-ignore-next-line complexity
    mutationFn: async () => {
      if (!orgSlug || !plugin) throw new Error('No organization selected')
      const capabilities: IntegrationCreate['capabilities'] = {}
      for (const [kind, state] of Object.entries(caps)) {
        capabilities[kind] = { enabled: state.enabled, options: state.options }
      }
      const created = await createIntegration(orgSlug, {
        capabilities,
        credentials,
        name: name.trim(),
        options,
        plugin: plugin.slug,
        slug: slug.trim(),
      })
      // Project-type assignments are set through a separate endpoint. Only
      // narrowed (non-empty) assignments need writing; zero = all types.
      for (const cap of plugin.capabilities) {
        const state = caps[cap.kind]
        if (state?.enabled && cap.project_scoped && state.assigned.length > 0) {
          await replaceCapabilityAssignments(
            orgSlug,
            created.slug,
            cap.kind as CapabilityKind,
            {
              assignments: state.assigned.map((project_type_slug) => ({
                default: false,
                env_payloads: {},
                identity_integration_slug: null,
                options: {},
                project_type_slug,
              })),
            },
          )
        }
      }
      return created
    },
    onSuccess: (created) => {
      if (orgSlug) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.integrations(orgSlug),
        })
      }
      onCreated(created)
    },
  })

  const requiredCreds = plugin?.credentials.filter((c) => c.required) ?? []
  const optionalCreds = plugin?.credentials.filter((c) => !c.required) ?? []

  // fallow-ignore-next-line complexity
  const validateConnection = (): boolean => {
    const next: Record<string, string> = {}
    if (!name.trim()) next.name = 'Name is required'
    if (!slug.trim()) next.slug = 'Slug is required'
    for (const opt of plugin?.options ?? []) {
      if (opt.required && !options[opt.name]) {
        next[`opt:${opt.name}`] = `${opt.label} is required`
      }
    }
    for (const cred of requiredCreds) {
      if (!credentials[cred.name]?.trim()) {
        next[`cred:${cred.name}`] = `${cred.label} is required`
      }
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  // fallow-ignore-next-line complexity
  const next = () => {
    if (step === 1 && !plugin) return
    if (step === 2 && !validateConnection()) return
    setStep((s) => Math.min(4, s + 1))
  }

  const back = () => {
    if (step === 1) {
      onCancel()
    } else {
      setStep((s) => s - 1)
    }
  }

  const setName_ = (value: string) => {
    setName(value)
    if (!slugEdited) setSlug(slugify(value))
  }

  return (
    <div className="max-w-3xl">
      <Button
        className="mb-3 pl-1.5"
        onClick={onCancel}
        size="sm"
        variant="ghost"
      >
        <ArrowLeft className="size-4" />
        Integrations
      </Button>
      <h1 className="text-primary mb-5 text-2xl font-semibold tracking-tight">
        New integration
      </h1>

      <Stepper current={step} />

      {createMutation.error && (
        <div className="mb-5">
          <ErrorBanner
            error={createMutation.error}
            title="Failed to create integration"
          />
        </div>
      )}

      {step === 1 && (
        <PluginStep
          onSelect={selectPlugin}
          plugins={plugins}
          selected={pluginSlug}
        />
      )}

      {step === 2 && plugin && (
        <div className="flex flex-col gap-6">
          <Card>
            <CardContent className="flex flex-col gap-4 p-5">
              <SectionLabel>Connection</SectionLabel>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="int-name">Name</Label>
                  <Input
                    id="int-name"
                    onChange={(e) => setName_(e.target.value)}
                    value={name}
                  />
                  {errors.name && <FieldError>{errors.name}</FieldError>}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="int-slug">Slug</Label>
                  <Input
                    className="font-mono"
                    id="int-slug"
                    onChange={(e) => {
                      setSlugEdited(true)
                      setSlug(e.target.value)
                    }}
                    value={slug}
                  />
                  {errors.slug && <FieldError>{errors.slug}</FieldError>}
                </div>
              </div>
            </CardContent>
          </Card>

          {plugin.options.length > 0 && (
            <Card>
              <CardContent className="flex flex-col gap-4 p-5">
                <SectionLabel>Options</SectionLabel>
                {plugin.options.map((opt) => (
                  <OptionField
                    error={errors[`opt:${opt.name}`]}
                    key={opt.name}
                    onChange={(value) =>
                      setOptions((o) => ({ ...o, [opt.name]: value }))
                    }
                    option={opt}
                    value={options[opt.name]}
                  />
                ))}
              </CardContent>
            </Card>
          )}

          {plugin.credentials.length > 0 && (
            <Card>
              <CardContent className="flex flex-col gap-4 p-5">
                <div className="flex items-center justify-between">
                  <SectionLabel>Credentials</SectionLabel>
                  <span className="text-tertiary text-xs">
                    Write-only, never echoed back
                  </span>
                </div>
                {/* fallow-ignore-next-line complexity */}
                {requiredCreds.map((cred) => (
                  <div className="flex flex-col gap-1.5" key={cred.name}>
                    <Label htmlFor={`cred-${cred.name}`}>
                      {cred.label}{' '}
                      <span className="text-danger text-xs">required</span>
                    </Label>
                    <CredentialInput
                      cred={cred}
                      onChange={(v) =>
                        setCredentials((c) => ({ ...c, [cred.name]: v }))
                      }
                      value={credentials[cred.name] ?? ''}
                    />
                    {cred.description && (
                      <FieldDescription text={cred.description} />
                    )}
                    {errors[`cred:${cred.name}`] && (
                      <FieldError>{errors[`cred:${cred.name}`]}</FieldError>
                    )}
                  </div>
                ))}
                {optionalCreds.length > 0 && (
                  <div className="flex flex-col gap-4">
                    <button
                      className="text-secondary hover:text-primary flex w-fit items-center gap-2 text-sm"
                      onClick={() => setShowOptionalCreds((v) => !v)}
                      type="button"
                    >
                      {showOptionalCreds ? 'Hide' : 'Show'} optional credentials
                    </button>
                    {showOptionalCreds &&
                      optionalCreds.map((cred) => (
                        <div className="flex flex-col gap-1.5" key={cred.name}>
                          <Label htmlFor={`cred-${cred.name}`}>
                            {cred.label}{' '}
                            <span className="text-tertiary text-xs">
                              optional
                            </span>
                          </Label>
                          <CredentialInput
                            cred={cred}
                            onChange={(v) =>
                              setCredentials((c) => ({ ...c, [cred.name]: v }))
                            }
                            value={credentials[cred.name] ?? ''}
                          />
                          {cred.description && (
                            <FieldDescription text={cred.description} />
                          )}
                        </div>
                      ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {step === 3 && plugin && (
        <div>
          <div className="text-primary mb-1 text-[15px] font-semibold">
            Capabilities
          </div>
          <div className="text-secondary mb-4 text-sm">
            Flip on what this integration should do. Each project-scoped
            capability applies to all project types unless you narrow it.
          </div>
          <Card>
            <CardContent className="p-0">
              {/* fallow-ignore-next-line complexity */}
              {plugin.capabilities.map((cap) => {
                const state = caps[cap.kind]
                if (!state) return null
                const meta = capabilityMeta(cap.kind)
                return (
                  <CapabilityRow
                    assignedTypeSlugs={state.assigned}
                    description={cap.description}
                    enabled={state.enabled}
                    key={cap.kind}
                    kind={cap.kind}
                    label={cap.label}
                    note={
                      cap.project_scoped
                        ? null
                        : 'Applies org-wide, not per project type.'
                    }
                    onAssignmentChange={(assigned) =>
                      setCaps((c) => ({
                        ...c,
                        [cap.kind]: { ...c[cap.kind], assigned },
                      }))
                    }
                    onOptionChange={(optName, value) =>
                      setCaps((c) => ({
                        ...c,
                        [cap.kind]: {
                          ...c[cap.kind],
                          options: {
                            ...c[cap.kind].options,
                            [optName]: value,
                          },
                        },
                      }))
                    }
                    onToggle={(enabled) =>
                      setCaps((c) => ({
                        ...c,
                        [cap.kind]: { ...c[cap.kind], enabled },
                      }))
                    }
                    options={cap.options}
                    optionValues={state.options}
                    projectScoped={
                      cap.project_scoped && (meta?.projectScoped ?? true)
                    }
                    projectTypes={projectTypes}
                  />
                )
              })}
            </CardContent>
          </Card>
        </div>
      )}

      {step === 4 && plugin && (
        <ReviewStep
          caps={caps}
          credentialLabels={plugin.credentials
            .filter((c) => credentials[c.name]?.trim())
            .map((c) => c.label)}
          name={name}
          plugin={plugin}
          projectTypes={projectTypes}
          slug={slug}
        />
      )}

      <div className="border-tertiary mt-6 flex items-center justify-between border-t pt-5">
        <Button onClick={back} variant="ghost">
          <ArrowLeft className="size-4" />
          Back
        </Button>
        {step < 4 ? (
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={step === 1 && !plugin}
            onClick={next}
          >
            Continue
            <ArrowRight className="size-4" />
          </Button>
        ) : (
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            <Check className="size-4" />
            Create integration
          </Button>
        )}
      </div>
    </div>
  )
}

// A credential input: a textarea for multi-line values (e.g. a PEM private
// key), otherwise a single-line input masked for secret fields.
function CredentialInput({
  cred,
  onChange,
  value,
}: {
  cred: PluginPackage['credentials'][number]
  onChange: (value: string) => void
  value: string
}) {
  if (cred.multiline) {
    return (
      <Textarea
        className="min-h-32 font-mono text-xs"
        id={`cred-${cred.name}`}
        onChange={(e) => onChange(e.target.value)}
        value={value}
      />
    )
  }
  return (
    <Input
      className="font-mono"
      id={`cred-${cred.name}`}
      onChange={(e) => onChange(e.target.value)}
      type={cred.secret === false ? 'text' : 'password'}
      value={value}
    />
  )
}

function FieldError({ children }: { children: React.ReactNode }) {
  return <span className="text-danger text-xs">{children}</span>
}

function initCapabilities(
  capabilities: PluginCapability[],
): Record<string, CapabilityState> {
  const state: Record<string, CapabilityState> = {}
  for (const cap of capabilities) {
    const options: Record<string, unknown> = {}
    for (const opt of cap.options) options[opt.name] = optionDefault(opt)
    state[cap.kind] = {
      assigned: [],
      enabled: cap.default_enabled,
      options,
    }
  }
  return state
}

function optionDefault(option: PluginOption): unknown {
  if (option.default !== undefined && option.default !== null) {
    return option.default
  }
  return option.type === 'boolean' ? false : ''
}

// fallow-ignore-next-line complexity
function OptionField({
  error,
  onChange,
  option,
  value,
}: {
  error?: string
  onChange: (value: unknown) => void
  option: PluginOption
  value: unknown
}) {
  if (option.choices && option.choices.length > 0) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label>{option.label}</Label>
        <div className="max-w-90">
          <Select
            onValueChange={onChange}
            value={typeof value === 'string' ? value : undefined}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select…" />
            </SelectTrigger>
            <SelectContent>
              {option.choices.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {option.description && <FieldDescription text={option.description} />}
        {error && <FieldError>{error}</FieldError>}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{option.label}</Label>
      <Input
        className={cn('max-w-90', option.type !== 'string' && 'font-mono')}
        onChange={(e) =>
          onChange(
            option.type === 'integer'
              ? e.target.value === ''
                ? null
                : Number(e.target.value)
              : e.target.value,
          )
        }
        type={option.type === 'integer' ? 'number' : 'text'}
        value={value === null || value === undefined ? '' : String(value)}
      />
      {option.description && <FieldDescription text={option.description} />}
      {error && <FieldError>{error}</FieldError>}
    </div>
  )
}

function PluginStep({
  onSelect,
  plugins,
  selected,
}: {
  onSelect: (p: PluginPackage) => void
  plugins: PluginPackage[]
  selected: null | string
}) {
  if (plugins.length === 0) {
    return (
      <Card>
        <CardContent className="text-secondary p-10 text-center text-sm">
          No enabled plugins are installed. Enable a plugin on the Plugins page
          first.
        </CardContent>
      </Card>
    )
  }
  return (
    <div>
      <div className="text-primary mb-1 text-[15px] font-semibold">
        Choose a plugin
      </div>
      <div className="text-secondary mb-4 text-sm">
        Only installed, enabled plugins are shown.
      </div>
      <div className="grid grid-cols-2 gap-3">
        {plugins.map((p) => {
          const isSelected = p.slug === selected
          return (
            <button
              className={cn(
                'flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors',
                isSelected
                  ? 'border-amber-border bg-amber-bg/40'
                  : 'border-secondary bg-primary hover:border-primary',
              )}
              key={p.slug}
              onClick={() => onSelect(p)}
              type="button"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="bg-secondary text-secondary flex size-8 items-center justify-center rounded-md">
                    <Package className="size-4" />
                  </span>
                  <div>
                    <div className="text-primary text-sm font-semibold">
                      {p.name}
                    </div>
                    <div className="text-tertiary font-mono text-xs">
                      {p.slug}
                    </div>
                  </div>
                </div>
                {isSelected && (
                  <CheckCircle2 className="text-amber-border size-5" />
                )}
              </div>
              {p.description && (
                <FieldDescription
                  className="text-secondary text-[13px] leading-snug"
                  text={p.description}
                />
              )}
              <div className="text-tertiary flex gap-2">
                {p.capabilities.map((cap) => {
                  const meta = capabilityMeta(cap.kind)
                  if (!meta) return null
                  const Icon = meta.icon
                  return (
                    <span key={cap.kind} title={cap.label}>
                      <Icon className="size-3.5" />
                    </span>
                  )
                })}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function ReviewStep({
  caps,
  credentialLabels,
  name,
  plugin,
  projectTypes,
  slug,
}: {
  caps: Record<string, CapabilityState>
  credentialLabels: string[]
  name: string
  plugin: PluginPackage
  projectTypes: { name: string; slug: string }[]
  slug: string
}) {
  const rows: { k: string; v: string }[] = [
    { k: 'Plugin', v: plugin.name },
    { k: 'Name', v: name },
    { k: 'Slug', v: slug },
    {
      k: 'Credentials',
      v: credentialLabels.length
        ? `${credentialLabels.join(', ')} set`
        : 'None',
    },
  ]
  const enabledCaps = plugin.capabilities.filter((c) => caps[c.kind]?.enabled)
  return (
    <div className="flex flex-col gap-5">
      <div className="text-primary text-[15px] font-semibold">
        Review &amp; create
      </div>
      <Card>
        <CardContent className="px-5 py-1">
          {rows.map((r) => (
            <div
              className="border-tertiary flex items-center justify-between gap-4 border-b py-3 last:border-b-0"
              key={r.k}
            >
              <span className="text-tertiary text-sm">{r.k}</span>
              <span className="text-primary text-sm font-medium">{r.v}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-5">
          <SectionLabel>Capabilities</SectionLabel>
          <div className="mt-3 flex flex-col gap-2">
            {enabledCaps.length === 0 && (
              <span className="text-tertiary text-sm">
                No capabilities enabled.
              </span>
            )}
            {/* fallow-ignore-next-line complexity */}
            {enabledCaps.map((cap) => {
              const state = caps[cap.kind]
              const meta = capabilityMeta(cap.kind)
              const Icon = meta?.icon
              const assign = !cap.project_scoped
                ? 'Org-wide'
                : state.assigned.length === 0
                  ? 'All project types'
                  : projectTypes
                      .filter((t) => state.assigned.includes(t.slug))
                      .map((t) => t.name)
                      .join(', ')
              return (
                <div className="flex items-center gap-2.5 py-1" key={cap.kind}>
                  {Icon && <Icon className="text-secondary size-4" />}
                  <span className="flex-1 text-sm font-medium">
                    {cap.label}
                  </span>
                  <span className="bg-amber-bg text-amber-text rounded px-2 py-0.5 text-xs">
                    {assign}
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-tertiary text-xs font-semibold tracking-wide uppercase">
      {children}
    </div>
  )
}

function Stepper({ current }: { current: number }) {
  return (
    <div className="mb-6 flex items-center">
      {/* fallow-ignore-next-line complexity */}
      {STEP_LABELS.map((label, i) => {
        const n = i + 1
        const done = n < current
        const active = n === current
        return (
          <div className="flex flex-1 items-center last:flex-none" key={label}>
            <div className="flex min-w-0 items-center gap-2">
              <span
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  active
                    ? 'bg-action text-action-foreground'
                    : done
                      ? 'bg-amber-bg text-amber-text'
                      : 'bg-secondary text-tertiary',
                )}
              >
                {done ? <Check className="size-3.5" /> : n}
              </span>
              <span
                className={cn(
                  'text-sm',
                  active ? 'font-medium text-primary' : 'text-tertiary',
                )}
              >
                {label}
              </span>
            </div>
            {n < STEP_LABELS.length && (
              <span className="bg-secondary mx-3 h-px flex-1" />
            )}
          </div>
        )
      })}
    </div>
  )
}
