import { useEffect, useRef, useState } from 'react'

import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { ArrowLeft, Lock, Package } from 'lucide-react'
import { toast } from 'sonner'

import { API_URL } from '@/api/client'
import {
  deleteIntegration,
  getIntegration,
  listCapabilityAssignments,
  listPluginPackages,
  listProjectTypes,
  listWebhooks,
  replaceCapabilityAssignments,
  updateIntegration,
  updateIntegrationCredentials,
} from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { InlineDisplay } from '@/components/ui/inline-edit/InlineDisplay'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk, Swap } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useInlineEdit } from '@/hooks/useInlineEdit'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { statusBadgeVariant } from '@/lib/status-colors'
import type {
  CapabilityKind,
  Integration,
  PluginOption,
  PluginPackage,
} from '@/types'

import { CapabilityRow } from './CapabilityRow'

interface IntegrationDetailProps {
  onBack: () => void
  seed: Integration | null
  slug: string
}

// fallow-ignore-next-line complexity
export function IntegrationDetail({
  onBack,
  seed,
  slug,
}: IntegrationDetailProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const queryClient = useQueryClient()

  const {
    data: integration,
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug && !!slug,
    initialData: seed ?? undefined,
    queryFn: ({ signal }) => getIntegration(orgSlug!, slug, signal),
    queryKey:
      orgSlug && slug
        ? queryKeys.integration(orgSlug, slug)
        : ['integration', slug],
  })

  const { data: plugins = [] } = useQuery({
    queryFn: ({ signal }) => listPluginPackages(signal),
    queryKey: queryKeys.pluginPackages(),
    staleTime: 60 * 1000,
  })

  const { data: projectTypes = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug!, signal),
    queryKey: orgSlug ? queryKeys.projectTypes(orgSlug) : ['projectTypes'],
  })

  const plugin = plugins.find((p) => p.slug === integration?.plugin) ?? null
  const pluginAvailable = !!plugin && plugin.enabled
  const editable = pluginAvailable

  // Gateway delivery URLs for the webhook-actions capability: the org's
  // webhooks implemented by this integration, each reachable externally
  // at <origin>/gateway/notifications<notification_path>.
  const hasWebhookCapability = !!plugin?.capabilities.some(
    (c) => c.kind === 'webhook-actions',
  )
  const { data: webhooks = [] } = useQuery({
    enabled: !!orgSlug && hasWebhookCapability,
    queryFn: ({ signal }) => listWebhooks(orgSlug!, signal),
    queryKey: ['webhooks', orgSlug],
  })
  const webhookUrls = webhooks
    .filter(
      (w) =>
        (w.third_party_service?.slug as string | undefined) ===
        integration?.slug,
    )
    .map((w) => ({
      name: w.name,
      url: `${gatewayOrigin()}/gateway/notifications${w.notification_path}`,
    }))

  // Load current project-type assignments for each project-scoped capability.
  const scopedKinds =
    plugin?.capabilities.filter((c) => c.project_scoped).map((c) => c.kind) ??
    []
  const assignmentQueries = useQueries({
    queries: scopedKinds.map((kind) => ({
      enabled: !!orgSlug && !!integration,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        listCapabilityAssignments(
          orgSlug!,
          slug,
          kind as CapabilityKind,
          signal,
        ),
      queryKey: ['capability-assignments', orgSlug, slug, kind],
    })),
  })
  const assignmentsByKind: Record<string, string[]> = {}
  scopedKinds.forEach((kind, i) => {
    assignmentsByKind[kind] = (assignmentQueries[i].data ?? []).map(
      (a) => a.project_type_slug,
    )
  })

  const invalidate = () => {
    if (orgSlug) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.integration(orgSlug, slug),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.integrations(orgSlug),
      })
    }
  }

  const patchMutation = useMutation({
    mutationFn: (data: Parameters<typeof updateIntegration>[2]) =>
      updateIntegration(orgSlug!, slug, data),
    onError: (err) => toast.error(`Save failed: ${extractApiErrorDetail(err)}`),
    onSuccess: invalidate,
  })

  const assignmentMutation = useMutation({
    mutationFn: ({ kind, slugs }: { kind: string; slugs: string[] }) =>
      replaceCapabilityAssignments(orgSlug!, slug, kind as CapabilityKind, {
        assignments: slugs.map((project_type_slug) => ({
          default: false,
          env_payloads: {},
          identity_integration_slug: null,
          options: {},
          project_type_slug,
        })),
      }),
    onError: (err) => toast.error(`Save failed: ${extractApiErrorDetail(err)}`),
    onSuccess: (_data, { kind }) => {
      void queryClient.invalidateQueries({
        queryKey: ['capability-assignments', orgSlug, slug, kind],
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteIntegration(orgSlug!, slug),
    onError: (err) =>
      toast.error(`Delete failed: ${extractApiErrorDetail(err)}`),
    onSuccess: () => {
      toast.success('Integration deleted')
      invalidate()
      onBack()
    },
  })

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pendingCred, setPendingCred] = useState<null | string>(null)
  const [pendingOpt, setPendingOpt] = useState<null | string>(null)

  if (error && !integration) {
    return <ErrorBanner error={error} title="Failed to load integration" />
  }

  // Write-only, per-field credential replacement: committing a single field
  // sends just that value; blank fields are never submitted, so untouched
  // credentials keep their current server value.
  const saveCredential = async (name: string, value: string) => {
    if (!orgSlug) return
    setPendingCred(name)
    try {
      await updateIntegrationCredentials(orgSlug, slug, { [name]: value })
      toast.success('Credentials updated')
      invalidate()
    } catch (err) {
      toast.error(`Save failed: ${extractApiErrorDetail(err)}`)
      throw err
    } finally {
      setPendingCred(null)
    }
  }

  const patchCapability = (
    kind: string,
    enabled: boolean,
    options: Record<string, unknown>,
  ) => {
    patchMutation.mutate({ capabilities: { [kind]: { enabled, options } } })
  }

  // Integration-level options (host, flavor, …) are merged server-side, so
  // a single-field patch leaves the rest untouched.
  const saveOption = async (name: string, value: unknown) => {
    setPendingOpt(name)
    try {
      await patchMutation.mutateAsync({ options: { [name]: value } })
      toast.success('Connection updated')
    } finally {
      setPendingOpt(null)
    }
  }

  return (
    <div className="max-w-4xl">
      <Button
        className="mb-3 pl-1.5"
        onClick={onBack}
        size="sm"
        variant="ghost"
      >
        <ArrowLeft className="size-4" />
        Integrations
      </Button>

      <Swap
        ready={!isLoading || !!integration}
        skeleton={
          <div className="space-y-4">
            <Sk h={32} w="40%" />
            <Sk h={160} />
            <Sk h={220} />
          </div>
        }
      >
        {integration && (
          <>
            {!pluginAvailable && (
              <Alert className="mb-4" variant="warning">
                The {integration.plugin} plugin is disabled or no longer
                installed. This integration is inactive and its capabilities are
                read-only.
              </Alert>
            )}

            <div className="mb-6 flex items-start justify-between gap-5">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-primary text-2xl font-semibold tracking-tight">
                  {integration.name}
                </h1>
                <span className="text-tertiary inline-flex items-center gap-1 font-mono text-xs">
                  <Package className="size-3" />
                  {integration.plugin}
                </span>
                <Badge variant={statusBadgeVariant(integration.status)}>
                  {integration.status}
                </Badge>
              </div>
            </div>

            <div className="flex flex-col gap-5">
              {/* Connection */}
              <Card>
                <CardContent className="p-5">
                  <div className="mb-4">
                    <h2 className="text-primary text-[17px] font-semibold">
                      Connection
                    </h2>
                  </div>

                  {plugin && plugin.options.length > 0 && (
                    <div className="mb-2">
                      {plugin.options.map((opt) => (
                        <OptionRow
                          key={opt.name}
                          onSave={(value) => saveOption(opt.name, value)}
                          option={opt}
                          pending={pendingOpt === opt.name}
                          readOnly={!editable}
                          value={integration.options[opt.name]}
                        />
                      ))}
                    </div>
                  )}

                  <div className="text-tertiary mt-4 mb-1 text-xs font-semibold tracking-wide uppercase">
                    Credentials
                  </div>
                  {(plugin?.credentials ?? []).map((cred) => (
                    <CredentialRow
                      cred={cred}
                      isSet={integration.credential_fields.includes(cred.name)}
                      key={cred.name}
                      onSave={(value) => saveCredential(cred.name, value)}
                      pending={pendingCred === cred.name}
                      readOnly={!editable}
                      value={integration.credential_values?.[cred.name]}
                    />
                  ))}
                  {(plugin?.credentials.length ?? 0) === 0 && (
                    <div className="text-tertiary text-sm">
                      This plugin requires no credentials.
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Capabilities */}
              <Card>
                <CardContent className="p-0">
                  <div className="flex items-center justify-between px-5 pt-4 pb-3">
                    <h2 className="text-primary text-[17px] font-semibold">
                      Capabilities
                    </h2>
                  </div>
                  <div className="border-tertiary border-t">
                    {/* fallow-ignore-next-line complexity */}
                    {(plugin?.capabilities ?? []).map((cap) => {
                      const toggle = integration.capabilities[cap.kind]
                      const enabled = toggle?.enabled ?? false
                      const options = toggle?.options ?? {}
                      // OAuth-redirect identity plugins need their callback URL
                      // registered with the provider (e.g. the GitHub App). It
                      // mirrors the backend's `_build_redirect_uri`. Device-flow
                      // identities (AWS IAM IC) use no redirect_uri, so omit it.
                      const callbackUrl =
                        cap.kind === 'identity' &&
                        integration.id &&
                        (plugin?.auth_type === 'oauth2' ||
                          plugin?.auth_type === 'oidc')
                          ? `${API_URL}/me/identities/${integration.id}/callback`
                          : undefined
                      return (
                        <CapabilityRow
                          assignedTypeSlugs={assignmentsByKind[cap.kind] ?? []}
                          callbackUrl={callbackUrl}
                          description={cap.description}
                          editable={editable}
                          enabled={enabled}
                          key={cap.kind}
                          kind={cap.kind}
                          label={cap.label}
                          note={
                            cap.project_scoped
                              ? null
                              : 'Applies org-wide, not per project type.'
                          }
                          onAssignmentChange={(slugs) =>
                            assignmentMutation.mutate({
                              kind: cap.kind,
                              slugs,
                            })
                          }
                          onOptionChange={(optName, value) =>
                            patchCapability(cap.kind, enabled, {
                              ...options,
                              [optName]: value,
                            })
                          }
                          onToggle={(nextEnabled) =>
                            patchCapability(cap.kind, nextEnabled, options)
                          }
                          options={cap.options}
                          optionValues={options}
                          projectScoped={cap.project_scoped}
                          projectTypes={projectTypes}
                          webhookUrls={
                            cap.kind === 'webhook-actions'
                              ? webhookUrls
                              : undefined
                          }
                        />
                      )
                    })}
                    {(plugin?.capabilities.length ?? 0) === 0 && (
                      <div className="text-tertiary p-5 text-sm">
                        No capabilities are available for this plugin.
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Danger zone */}
              <Card className="border-danger">
                <CardContent className="p-5">
                  <h2 className="text-danger text-[17px] font-semibold">
                    Danger zone
                  </h2>
                  <div className="flex items-center justify-between gap-4 pt-3">
                    <div>
                      <div className="text-primary text-sm font-medium">
                        Disable integration
                      </div>
                      <div className="text-secondary text-sm">
                        Stops all capabilities. Configuration is kept.
                      </div>
                    </div>
                    <Button
                      disabled={
                        integration.status === 'inactive' ||
                        patchMutation.isPending
                      }
                      onClick={() =>
                        patchMutation.mutate({ status: 'inactive' })
                      }
                      variant="secondary"
                    >
                      {integration.status === 'inactive'
                        ? 'Disabled'
                        : 'Disable'}
                    </Button>
                  </div>
                  <div className="border-tertiary mt-3.5 flex items-center justify-between gap-4 border-t pt-3.5">
                    <div>
                      <div className="text-primary text-sm font-medium">
                        Delete integration
                      </div>
                      <div className="text-secondary text-sm">
                        Removes credentials and unlinks connected projects.
                        Cannot be undone.
                      </div>
                    </div>
                    <Button
                      className="border-danger bg-danger text-danger border"
                      onClick={() => setConfirmDelete(true)}
                      variant="ghost"
                    >
                      Delete…
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>

            <ConfirmDialog
              confirmLabel="Delete"
              description={`Delete "${integration.name}"? This removes its credentials and unlinks connected projects. This cannot be undone.`}
              onCancel={() => setConfirmDelete(false)}
              onConfirm={() => {
                setConfirmDelete(false)
                deleteMutation.mutate()
              }}
              open={confirmDelete}
              title="Delete integration"
            />
          </>
        )}
      </Swap>
    </div>
  )
}

// One credential field, click-to-edit inline. The stored secret is never read
// back, so editing starts from an empty draft; committing a non-empty value
// replaces it, and an empty commit is a no-op that keeps the current value.
// fallow-ignore-next-line complexity
// fallow-ignore-next-line complexity
function CredentialRow({
  cred,
  isSet,
  onSave,
  pending,
  readOnly,
  value,
}: {
  cred: PluginPackage['credentials'][number]
  isSet: boolean
  onSave: (value: string) => Promise<void>
  pending: boolean
  readOnly: boolean
  // Current value for non-secret fields (echoed back by the API); secret
  // values are never sent, so undefined for those.
  value?: string
}) {
  const isSecret = cred.secret !== false
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)
  // Non-secret fields edit from their current value; secret fields start
  // blank (the stored value is never read back).
  const edit = useInlineEdit<string>({
    initial: value ?? '',
    onCommit: async (next) => {
      if (next.trim() && next !== value) await onSave(next)
    },
  })

  useEffect(() => {
    if (edit.isEditing) inputRef.current?.focus()
  }, [edit.isEditing])

  return (
    <div className="border-tertiary flex items-center justify-between gap-4 border-b py-2.5 last:border-b-0">
      <span className="text-secondary flex items-center gap-2 text-[13px]">
        {cred.label}
        {!cred.required && (
          <span className="text-tertiary text-xs">optional</span>
        )}
      </span>
      {edit.isEditing ? (
        <span className="flex flex-col items-end">
          {cred.multiline ? (
            <Textarea
              className="min-h-32 w-96 py-1 font-mono text-xs"
              onBlur={edit.handleBlur}
              onChange={(e) => edit.setDraft(e.target.value)}
              ref={inputRef as React.RefObject<HTMLTextAreaElement>}
              value={edit.draft}
            />
          ) : (
            <Input
              className="h-7 w-56 py-1 font-mono"
              onBlur={edit.handleBlur}
              onChange={(e) => edit.setDraft(e.target.value)}
              onKeyDown={edit.handleKeyDown}
              ref={inputRef as React.RefObject<HTMLInputElement>}
              type={isSecret ? 'password' : 'text'}
              value={edit.draft}
            />
          )}
          {edit.error && (
            <span className="mt-1 text-xs text-red-600">{edit.error}</span>
          )}
        </span>
      ) : (
        <InlineDisplay
          hasValue
          onClick={edit.enter}
          pending={pending}
          readOnly={readOnly}
        >
          <span className="text-tertiary inline-flex items-center gap-1.5 text-sm">
            {isSecret && <Lock className="size-3" />}
            {!isSecret && value ? (
              <span className="text-primary max-w-72 truncate font-mono">
                {value}
              </span>
            ) : isSet ? (
              <span className="text-success">set</span>
            ) : (
              'not set'
            )}
          </span>
        </InlineDisplay>
      )}
    </div>
  )
}

// fallow-ignore-next-line complexity
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

// The gateway is served from the same public origin as the API (the
// ingress mounts /api and /gateway side by side). API_URL may be
// path-only in same-origin deployments, so fall back to the page origin.
function gatewayOrigin(): string {
  try {
    return new URL(API_URL).origin
  } catch {
    return window.location.origin
  }
}

// One integration-level option (host, flavor, …), click-to-edit inline and
// saved on commit. Choices render a Select; booleans a Switch; everything
// else a text/number input.
// fallow-ignore-next-line complexity
function OptionRow({
  onSave,
  option,
  pending,
  readOnly,
  value,
}: {
  onSave: (value: unknown) => Promise<void> | void
  option: PluginOption
  pending: boolean
  readOnly: boolean
  value: unknown
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const current = value === null || value === undefined ? '' : String(value)
  const edit = useInlineEdit<string>({
    initial: current,
    onCommit: async (next) => {
      const trimmed = next.trim()
      if (trimmed === current) return
      await onSave(
        option.type === 'integer'
          ? trimmed === ''
            ? null
            : Number(trimmed)
          : trimmed,
      )
    },
  })

  useEffect(() => {
    if (edit.isEditing) inputRef.current?.focus()
  }, [edit.isEditing])

  const label = (
    <span className="text-secondary text-[13px]">{option.label}</span>
  )
  const rowClass =
    'border-tertiary flex items-center justify-between gap-4 border-b py-2.5 last:border-b-0'

  if (option.type === 'boolean') {
    return (
      <div className={rowClass}>
        {label}
        <Switch
          checked={value === true}
          disabled={readOnly || pending}
          onCheckedChange={(checked) => onSave(checked)}
        />
      </div>
    )
  }

  if (option.choices && option.choices.length > 0) {
    return (
      <div className={rowClass}>
        {label}
        {readOnly ? (
          <span className="text-primary font-mono text-sm">
            {formatValue(value)}
          </span>
        ) : (
          <Select
            disabled={pending}
            onValueChange={(v) => onSave(v)}
            value={typeof value === 'string' ? value : undefined}
          >
            <SelectTrigger className="h-7 w-56">
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
        )}
      </div>
    )
  }

  return (
    <div className={rowClass}>
      {label}
      {edit.isEditing ? (
        <span className="flex flex-col items-end">
          <Input
            className="h-7 w-56 py-1 font-mono"
            onBlur={edit.handleBlur}
            onChange={(e) => edit.setDraft(e.target.value)}
            onKeyDown={edit.handleKeyDown}
            ref={inputRef}
            type={option.type === 'integer' ? 'number' : 'text'}
            value={edit.draft}
          />
          {edit.error && (
            <span className="mt-1 text-xs text-red-600">{edit.error}</span>
          )}
        </span>
      ) : (
        <InlineDisplay
          hasValue
          onClick={edit.enter}
          pending={pending}
          readOnly={readOnly}
        >
          <span className="text-primary font-mono text-sm">
            {formatValue(value)}
          </span>
        </InlineDisplay>
      )}
    </div>
  )
}
