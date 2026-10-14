import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createAgentMarketplace,
  deleteAgentMarketplace,
  getAgentPlatformConfig,
  listAgentMarketplaces,
  putAgentPlatformConfig,
  syncAgentMarketplace,
} from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import type {
  AgentMarketplace,
  AgentPlatformConfig,
  AgentPlatformConfigResponse,
} from '@/types'

import { parseLabels } from './agentDraft'
import { Field } from './OverviewTab'

const MODES: AgentPlatformConfig['permission_mode'][] = [
  'plan',
  'default',
  'acceptEdits',
  'bypassPermissions',
]

const onError = (err: unknown) => toast.error(extractApiErrorDetail(err))

interface ConfigForm {
  allowedTools: string
  approvalTools: string
  config: AgentPlatformConfig
  deniedTools: string
  hooks: string
}

/**
 * The organization's base agent configuration and its plugin
 * marketplaces (ADR 0022). Agents can only narrow the configuration.
 * Each save writes a new version; a task pins the version it starts
 * with.
 */
export function PlatformPage() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canWrite = useHasPermission('agent_platform_config:write')
  const config = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getAgentPlatformConfig(orgSlug!, signal),
    queryKey: queryKeys.agentPlatformConfig(orgSlug ?? ''),
  })
  const marketplaces = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listAgentMarketplaces(orgSlug!, signal),
    queryKey: queryKeys.agentMarketplaces(orgSlug ?? ''),
  })

  if (!orgSlug) {
    return (
      <div className="text-tertiary p-8 text-center">
        Select an organization to see its agent platform.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-6 p-8">
      {!canWrite && (
        <Alert>
          You can read this page. Changes need the agent_platform_config:write
          permission.
        </Alert>
      )}
      {(config.error || marketplaces.error) && (
        <ErrorBanner
          error={config.error ?? marketplaces.error}
          title="Failed to load the agent platform"
        />
      )}
      <MarketplacesCard
        canWrite={canWrite}
        marketplaces={marketplaces.data ?? []}
        orgSlug={orgSlug}
      />
      {config.data && (
        <ConfigCard
          canWrite={canWrite}
          // A new version resets the form to what the API stored.
          key={config.data.version ?? 0}
          marketplaces={marketplaces.data ?? []}
          orgSlug={orgSlug}
          stored={config.data}
        />
      )}
    </div>
  )
}

function MarketplacesCard({
  canWrite,
  marketplaces,
  orgSlug,
}: {
  canWrite: boolean
  marketplaces: AgentMarketplace[]
  orgSlug: string
}) {
  const queryClient = useQueryClient()
  const [slug, setSlug] = useState('')
  const [url, setUrl] = useState('')
  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.agentMarketplaces(orgSlug),
    })
  const report = (m: AgentMarketplace) => {
    if (m.sync_error) toast.error(`Sync of ${m.slug} failed: ${m.sync_error}`)
    else toast.success(`Synced ${m.slug}: ${m.plugins?.length ?? 0} plugins`)
  }
  const create = useMutation({
    mutationFn: () => createAgentMarketplace(orgSlug, { slug, url }),
    onError,
    onSuccess: (m) => {
      setSlug('')
      setUrl('')
      report(m)
      void refresh()
    },
  })
  const sync = useMutation({
    mutationFn: (s: string) => syncAgentMarketplace(orgSlug, s),
    onError,
    onSuccess: (m) => {
      report(m)
      void refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (s: string) => deleteAgentMarketplace(orgSlug, s),
    onError,
    onSuccess: () => void refresh(),
  })

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-tertiary border-b px-5 py-3.5">
        <div className="text-[15px] font-medium">Plugin marketplaces</div>
        <p className="text-tertiary text-xs">
          Claude Code plugin marketplaces, read through the organization's
          GitHub integration at the head of the default branch.
        </p>
      </div>
      {marketplaces.length === 0 ? (
        <p className="text-tertiary px-5 py-4 text-sm">No marketplaces.</p>
      ) : (
        <ul className="divide-tertiary divide-y">
          {marketplaces.map((m) => (
            <li className="flex items-center gap-3 px-5 py-2.5" key={m.slug}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{m.slug}</span>
                  {m.name && (
                    <span className="text-tertiary font-mono text-xs">
                      {m.name}
                    </span>
                  )}
                  {m.sync_error && (
                    <Badge title={m.sync_error} variant="danger">
                      sync failed
                    </Badge>
                  )}
                </div>
                <div className="text-secondary truncate font-mono text-xs">
                  {m.url}
                </div>
              </div>
              <span className="text-secondary text-xs whitespace-nowrap">
                {m.plugins?.length ?? 0} plugins
              </span>
              <span className="text-tertiary font-mono text-xs">
                {m.head_sha?.slice(0, 7) ?? '—'}
              </span>
              <span className="text-tertiary text-xs whitespace-nowrap">
                {m.synced_at ? formatRelativeDate(m.synced_at) : 'never'}
              </span>
              {canWrite && (
                <>
                  <Button
                    aria-label={`Sync ${m.slug}`}
                    disabled={sync.isPending}
                    onClick={() => sync.mutate(m.slug)}
                    size="sm"
                    variant="ghost"
                  >
                    <RefreshCw className="size-3.5" />
                  </Button>
                  <Button
                    aria-label={`Delete ${m.slug}`}
                    onClick={() => remove.mutate(m.slug)}
                    size="sm"
                    variant="ghost"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form
          className="border-tertiary flex items-end gap-3 border-t px-5 py-3"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          <Field htmlFor="marketplace-slug" label="Slug">
            <Input
              id="marketplace-slug"
              onChange={(e) => setSlug(e.target.value)}
              placeholder="claude-code"
              value={slug}
            />
          </Field>
          <div className="flex-1">
            <Field htmlFor="marketplace-url" label="Git URL">
              <Input
                id="marketplace-url"
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/anthropics/claude-code"
                value={url}
              />
            </Field>
          </div>
          <Button disabled={!slug || !url || create.isPending} type="submit">
            Add marketplace
          </Button>
        </form>
      )}
    </Card>
  )
}

const csv = (values?: null | string[]) => (values ?? []).join(', ')

function ConfigCard({
  canWrite,
  marketplaces,
  orgSlug,
  stored,
}: {
  canWrite: boolean
  marketplaces: AgentMarketplace[]
  orgSlug: string
  stored: AgentPlatformConfigResponse
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<ConfigForm>(() => ({
    allowedTools:
      stored.config.allowed_tools == null
        ? ''
        : csv(stored.config.allowed_tools),
    approvalTools: csv(stored.config.approval_tools),
    config: stored.config,
    deniedTools: csv(stored.config.denied_tools),
    hooks: JSON.stringify(stored.config.hooks ?? {}, null, 2),
  }))
  const [hooksError, setHooksError] = useState('')
  const config = form.config
  const setConfig = (patch: Partial<AgentPlatformConfig>) =>
    setForm((f) => ({ ...f, config: { ...f.config, ...patch } }))
  const upstream = config.model_upstream ?? { kind: 'anthropic' as const }
  const sandbox = {
    allow_unsandboxed_commands:
      config.sandbox?.allow_unsandboxed_commands ?? true,
    enabled: config.sandbox?.enabled ?? false,
  }
  const allowed = new Set(config.allowed_marketplaces ?? [])
  const defaults = config.default_plugins ?? []

  const save = useMutation({
    mutationFn: (body: AgentPlatformConfig) =>
      putAgentPlatformConfig(orgSlug, body),
    onError,
    onSuccess: (saved) => {
      toast.success(`Saved version ${saved.version}`)
      queryClient.setQueryData(queryKeys.agentPlatformConfig(orgSlug), saved)
    },
  })

  const onSave = () => {
    let hooks: Record<string, unknown>
    try {
      hooks = form.hooks.trim() ? JSON.parse(form.hooks) : {}
    } catch {
      setHooksError('Enter a JSON object')
      return
    }
    setHooksError('')
    save.mutate({
      ...config,
      allowed_tools: form.allowedTools.trim()
        ? parseLabels(form.allowedTools)
        : null,
      approval_tools: parseLabels(form.approvalTools),
      denied_tools: parseLabels(form.deniedTools),
      hooks,
    })
  }

  const toggleDefault = (marketplace: string, plugin: string, on: boolean) =>
    setConfig({
      default_plugins: on
        ? [...defaults, { marketplace, plugin }]
        : defaults.filter(
            (p) => !(p.marketplace === marketplace && p.plugin === plugin),
          ),
    })

  return (
    <Card className="flex flex-col gap-5 p-5">
      <div className="flex items-center gap-3">
        <div>
          <div className="text-[15px] font-medium">Base configuration</div>
          <p className="text-tertiary text-xs">
            {stored.version
              ? `Version ${stored.version}, saved ${formatRelativeDate(stored.created_at ?? '')} by ${stored.created_by}`
              : 'No version yet. The defaults apply.'}
          </p>
        </div>
        {canWrite && (
          <Button
            className="ml-auto"
            disabled={save.isPending}
            onClick={onSave}
          >
            Save version
          </Button>
        )}
      </div>
      <fieldset className="grid grid-cols-3 gap-4" disabled={!canWrite}>
        <Field htmlFor="upstream-kind" label="Model upstream">
          <Select
            onValueChange={(kind) =>
              setConfig({
                model_upstream: {
                  ...upstream,
                  kind: kind as 'anthropic' | 'litellm',
                },
              })
            }
            value={upstream.kind ?? 'anthropic'}
          >
            <SelectTrigger id="upstream-kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="anthropic">Anthropic API</SelectItem>
              <SelectItem value="litellm">LiteLLM gateway</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field htmlFor="upstream-url" label="Base URL">
          <Input
            id="upstream-url"
            onChange={(e) =>
              setConfig({
                model_upstream: {
                  ...upstream,
                  base_url: e.target.value || null,
                },
              })
            }
            placeholder="The Anthropic API"
            value={upstream.base_url ?? ''}
          />
        </Field>
        <Field help="A secret:// reference." htmlFor="upstream-key" label="Key">
          <Input
            className="font-mono text-xs"
            id="upstream-key"
            onChange={(e) =>
              setConfig({
                model_upstream: {
                  ...upstream,
                  key_ref: e.target.value || null,
                },
              })
            }
            placeholder="secret://anthropic/api_key"
            value={upstream.key_ref ?? ''}
          />
        </Field>
        <Field
          help="Agents can set a stricter mode only."
          htmlFor="permission-mode"
          label="Permission mode"
        >
          <Select
            onValueChange={(mode) =>
              setConfig({
                permission_mode: mode as AgentPlatformConfig['permission_mode'],
              })
            }
            value={config.permission_mode ?? 'default'}
          >
            <SelectTrigger id="permission-mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODES.map((mode) => (
                <SelectItem key={mode} value={mode!}>
                  {mode}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Sandbox">
          <div className="flex flex-col gap-2 pt-1 text-sm">
            <label className="flex items-center gap-2">
              <Switch
                checked={!!config.sandbox?.enabled}
                onCheckedChange={(enabled) =>
                  setConfig({ sandbox: { ...sandbox, enabled } })
                }
              />
              Require the sandbox
            </label>
            <label className="flex items-center gap-2">
              <Switch
                checked={config.sandbox?.allow_unsandboxed_commands ?? true}
                onCheckedChange={(on) =>
                  setConfig({
                    sandbox: {
                      ...sandbox,
                      allow_unsandboxed_commands: on,
                    },
                  })
                }
              />
              Allow unsandboxed commands
            </label>
          </div>
        </Field>
        <div />
        <Field
          help="Built-in tools, separated by commas. Empty allows all."
          htmlFor="allowed-tools"
          label="Allowed tools"
        >
          <Input
            id="allowed-tools"
            onChange={(e) =>
              setForm((f) => ({ ...f, allowedTools: e.target.value }))
            }
            placeholder="All tools"
            value={form.allowedTools}
          />
        </Field>
        <Field
          help="Agents can deny more."
          htmlFor="denied-tools"
          label="Denied tools"
        >
          <Input
            id="denied-tools"
            onChange={(e) =>
              setForm((f) => ({ ...f, deniedTools: e.target.value }))
            }
            placeholder="None"
            value={form.deniedTools}
          />
        </Field>
        <Field
          help="Need approval when an automation starts the task."
          htmlFor="approval-tools"
          label="Approval tools"
        >
          <Input
            id="approval-tools"
            onChange={(e) =>
              setForm((f) => ({ ...f, approvalTools: e.target.value }))
            }
            placeholder="None"
            value={form.approvalTools}
          />
        </Field>
      </fieldset>
      <fieldset className="grid grid-cols-2 gap-4" disabled={!canWrite}>
        <Field
          help="Put before the system prompt of each agent."
          htmlFor="prompt-prefix"
          label="System prompt prefix"
        >
          <Textarea
            id="prompt-prefix"
            onChange={(e) =>
              setConfig({ system_prompt_prefix: e.target.value })
            }
            rows={5}
            value={config.system_prompt_prefix ?? ''}
          />
        </Field>
        <Field
          error={hooksError}
          help="Agent SDK hooks, as JSON. Agents cannot change them."
          htmlFor="hooks"
          label="Hooks"
        >
          <Textarea
            className="font-mono text-xs"
            id="hooks"
            onChange={(e) => setForm((f) => ({ ...f, hooks: e.target.value }))}
            rows={5}
            value={form.hooks}
          />
        </Field>
      </fieldset>
      <section className="flex flex-col gap-2">
        <div className="text-overline text-tertiary uppercase">
          Allowed marketplaces and default plugins
        </div>
        {marketplaces.length === 0 && (
          <p className="text-tertiary text-sm">Add a marketplace first.</p>
        )}
        {marketplaces.map((m) => (
          <div className="border-tertiary rounded-lg border" key={m.slug}>
            <label className="flex items-center gap-2 px-3 py-2 text-sm">
              <Checkbox
                checked={allowed.has(m.slug)}
                disabled={!canWrite}
                onCheckedChange={(on) =>
                  setConfig({
                    allowed_marketplaces: on
                      ? [...allowed, m.slug]
                      : [...allowed].filter((s) => s !== m.slug),
                    default_plugins: on
                      ? defaults
                      : defaults.filter((p) => p.marketplace !== m.slug),
                  })
                }
              />
              <span className="font-medium">{m.slug}</span>
              <span className="text-tertiary font-mono text-xs">{m.url}</span>
            </label>
            {allowed.has(m.slug) && (
              <div className="border-tertiary grid grid-cols-3 gap-x-4 gap-y-1 border-t px-3 py-2">
                {(m.plugins ?? []).map((p) => (
                  <label
                    className="flex items-center gap-2 font-mono text-xs"
                    key={p.name}
                    title={p.description ?? undefined}
                  >
                    <Checkbox
                      checked={defaults.some(
                        (d) => d.marketplace === m.slug && d.plugin === p.name,
                      )}
                      disabled={!canWrite || p.path == null}
                      onCheckedChange={(on) =>
                        toggleDefault(m.slug, p.name, on === true)
                      }
                    />
                    {p.name}
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
      </section>
    </Card>
  )
}
