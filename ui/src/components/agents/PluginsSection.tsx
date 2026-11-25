import { useQuery } from '@tanstack/react-query'
import { Check, ChevronRight, X } from 'lucide-react'

import {
  getAgentPlatformConfig,
  listAgentMarketplaces,
  listSecretProviders,
} from '@/api/endpoints'
import type { SecretBinding } from '@/components/admin/secrets/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { ErrorBanner } from '@/components/ui/error-banner'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentMarketplace, AgentPlugin, CatalogServer } from '@/types'

import { bindingOf, canSupplyRunner, covers, fieldReferences } from './access'
import type { SettingsDraft } from './agentDraft'
import { type GrantAgent, useAgentGrant } from './useAgentGrant'

const HEADER_PURPOSE = 'mcp_header'

const NO_SECRET = '__none__'

type ChangeSetting = (setting: ServerSetting) => ServerSetting

type ServerSetting = AgentPlugin['server_settings'][string]

const DEFAULT_SETTING: ServerSetting = { enabled: true, secrets: {} }

interface HeaderPicker {
  bindings: SecretBinding[]
  canGrant: (binding: SecretBinding) => boolean
  covered: (bindingId: string) => boolean
  grant: (reference: string) => void
  isPending: boolean
  loaded: boolean
  missing: null | string
  references: string[]
  showGrant: boolean
}

interface PluginsSectionProps {
  agent: GrantAgent | null
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

const short = (sha?: null | string) => (sha ? sha.slice(0, 7) : '')

const entry = (
  marketplace: string,
  plugin: string,
  server_settings: AgentPlugin['server_settings'] = {},
): AgentPlugin => ({ marketplace, mcp_servers: [], plugin, server_settings })

const same = (p: AgentPlugin, marketplace: string, plugin: string) =>
  p.marketplace === marketplace && p.plugin === plugin

const httpsOrigin = (url?: null | string): null | string => {
  try {
    const parsed = new URL(url ?? '')
    return parsed.protocol === 'https:' ? parsed.origin : null
  } catch {
    return null
  }
}

const hasSecrets = (setting?: ServerSetting) =>
  Object.keys(setting?.secrets ?? {}).length > 0

const headerVariables = (server: CatalogServer): string[] =>
  server.type === 'http' || server.type === 'sse'
    ? [...new Set(Object.values(server.headers).flat())]
    : []

const withSecret = (
  setting: ServerSetting,
  variable: string,
  reference: null | string,
  origin: string,
): ServerSetting => {
  const kept = setting.origin === origin ? setting.secrets : {}
  const { [variable]: _removed, ...rest } = kept
  const secrets = reference ? { ...rest, [variable]: reference } : rest
  return { ...setting, origin, secrets }
}

const settled = (setting: ServerSetting): null | ServerSetting => {
  if (hasSecrets(setting)) return setting
  return setting.enabled ? null : { enabled: false, secrets: {} }
}

/**
 * The plugins that the runner loads for the agent (ADR 0022), from the
 * marketplaces that the organization allows. The organization
 * configuration is the upper limit; the API pins each plugin to a
 * marketplace commit. A plugin's MCP servers come with it: while the
 * plugin is on, the agent can use all of their tools, unless it turns a
 * server off. Turning off a server of a default plugin adds an agent
 * entry for the plugin, which holds only the server settings.
 */
export function PluginsSection({
  agent,
  onChange,
  orgSlug,
  value,
}: PluginsSectionProps) {
  const set = (patch: Partial<SettingsDraft>) =>
    onChange({ ...value, ...patch })
  const config = useQuery({
    queryFn: ({ signal }) => getAgentPlatformConfig(orgSlug, signal),
    queryKey: queryKeys.agentPlatformConfig(orgSlug),
  })
  const marketplaces = useQuery({
    queryFn: ({ signal }) => listAgentMarketplaces(orgSlug, signal),
    queryKey: queryKeys.agentMarketplaces(orgSlug),
  })
  const access = useAgentGrant(orgSlug, agent)
  const canReadProviders = useHasPermission('secret_provider:read', orgSlug)
  const canList = access.canRead && canReadProviders
  const providers = useQuery({
    enabled: canList,
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })

  const allowed = new Set(config.data?.config.allowed_marketplaces ?? [])
  const defaults = config.data?.config.default_plugins ?? []
  const shown = (marketplaces.data ?? []).filter((m) => allowed.has(m.slug))
  const known = new Set(
    shown.flatMap((m) => m.plugins?.map((p) => `${m.slug}/${p.name}`) ?? []),
  )
  const orphans = value.plugins.filter(
    (p) => !known.has(`${p.marketplace}/${p.plugin}`),
  )

  const toggle = (marketplace: string, plugin: string, on: boolean) =>
    set({
      plugins: on
        ? [...value.plugins, entry(marketplace, plugin)]
        : value.plugins.filter((p) => !same(p, marketplace, plugin)),
    })
  // A plugin without `sha` is pinned to the newest synced commit.
  const repin = (target: AgentPlugin) =>
    set({
      plugins: value.plugins.map((p) =>
        p === target ? entry(p.marketplace, p.plugin, p.server_settings) : p,
      ),
    })
  const changeServer = (
    marketplace: string,
    plugin: string,
    server: string,
    change: ChangeSetting,
  ) => {
    const current = value.plugins.find((p) => same(p, marketplace, plugin))
    const { [server]: previous = DEFAULT_SETTING, ...rest } =
      current?.server_settings ?? {}
    const next = settled(change(previous))
    const settings = next ? { ...rest, [server]: next } : rest
    const isDefault = defaults.some((d) => same(d, marketplace, plugin))
    if (isDefault && Object.keys(settings).length === 0) {
      set({ plugins: value.plugins.filter((p) => p !== current) })
    } else if (!current) {
      set({
        plugins: [...value.plugins, entry(marketplace, plugin, settings)],
      })
    } else {
      set({
        plugins: value.plugins.map((p) =>
          p === current ? { ...p, server_settings: settings } : p,
        ),
      })
    }
  }

  const headerProviders = new Set(
    (providers.data ?? [])
      .filter((provider) => provider.enabled && provider.type !== 'github_app')
      .map((provider) => provider.id),
  )
  const bindings = access.bindings.data ?? []
  const picker: HeaderPicker = {
    bindings,
    canGrant: access.canGrant,
    covered: (bindingId) =>
      covers(access.mine, bindingId, HEADER_PURPOSE, 'file_descriptor'),
    grant: (reference) => {
      const binding = bindingOf(bindings, reference)
      if (binding) access.ensure(binding, HEADER_PURPOSE, 'file_descriptor')
    },
    isPending: access.save.isPending,
    loaded:
      access.bindings.isSuccess &&
      access.grants.isSuccess &&
      providers.isSuccess,
    missing: canList
      ? null
      : 'You need secret_binding:read, secret_grant:read, and secret_provider:read to pick secrets.',
    references: fieldReferences(
      bindings.filter(
        (binding) =>
          canSupplyRunner(binding) && headerProviders.has(binding.provider_id),
      ),
    ),
    showGrant: Boolean(agent) && access.canRead,
  }

  return (
    <div className="flex flex-col gap-6">
      {(config.error || marketplaces.error) && (
        <ErrorBanner
          error={config.error ?? marketplaces.error}
          title="Failed to load the plugin marketplaces"
        />
      )}
      <section className="flex flex-col gap-3">
        <div>
          <div className="text-overline text-tertiary uppercase">Plugins</div>
          <p className="text-tertiary mt-1 text-xs">
            Skills, commands, subagents, and MCP servers from the marketplaces
            that the organization allows (Agents › Platform). While a plugin is
            on, the agent can use every tool of its MCP servers. A save pins
            each new plugin to the commit that Imbi synced last. A secret picked
            for a header goes only to the origin of the server URL, and picking
            it grants the agent mcp_header for it at once.
          </p>
        </div>
        {shown.length === 0 && !config.isLoading && (
          <p className="text-tertiary text-sm">
            The organization allows no marketplace yet.
          </p>
        )}
        {shown.map((marketplace) => (
          <MarketplacePlugins
            defaults={defaults}
            key={marketplace.slug}
            marketplace={marketplace}
            onRepin={repin}
            onServer={changeServer}
            onToggle={toggle}
            picker={picker}
            selected={value.plugins}
          />
        ))}
        {orphans.length > 0 && (
          <div className="border-tertiary rounded-lg border p-3">
            <div className="text-warning text-xs">
              Not in an allowed marketplace now. Runners leave these out.
            </div>
            {orphans.map((p) => (
              <label
                className="mt-2 flex items-center gap-2 font-mono text-xs"
                key={`${p.marketplace}/${p.plugin}`}
              >
                <Checkbox
                  checked
                  onCheckedChange={() => toggle(p.marketplace, p.plugin, false)}
                />
                {p.plugin}@{p.marketplace}
              </label>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function HeaderSecret({
  disabled,
  label,
  onChange,
  picker,
  value,
  variable,
}: {
  disabled: boolean
  label: string
  onChange: (reference: null | string) => void
  picker: HeaderPicker
  value: string
  variable: string
}) {
  const usable = picker.references.includes(value)
  const options =
    value && !usable ? [...picker.references, value] : picker.references
  const binding = usable ? bindingOf(picker.bindings, value) : undefined
  const covered = binding ? picker.covered(binding.id) : false
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-secondary font-mono">{variable}</span>
      <Select
        disabled={disabled}
        onValueChange={(next) => onChange(next === NO_SECRET ? null : next)}
        value={value || NO_SECRET}
      >
        <SelectTrigger aria-label={label} className="h-7 w-auto text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_SECRET}>No secret</SelectItem>
          {options.map((reference) => (
            <SelectItem key={reference} value={reference}>
              {reference}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {picker.loaded && value && !usable && (
        <span className="text-danger">
          This secret cannot fill a header. Pick another.
        </span>
      )}
      {binding && picker.showGrant && (
        <>
          {covered ? (
            <Check aria-label="Granted" className="text-success size-4" />
          ) : (
            <X aria-label="Not granted" className="text-tertiary size-4" />
          )}
          <span className="text-tertiary font-mono">{HEADER_PURPOSE}</span>
          {!covered && picker.canGrant(binding) && (
            <Button
              disabled={picker.isPending}
              onClick={() => picker.grant(value)}
              size="sm"
              variant="outline"
            >
              Grant
            </Button>
          )}
        </>
      )}
    </div>
  )
}

function MarketplacePlugins({
  defaults,
  marketplace,
  onRepin,
  onServer,
  onToggle,
  picker,
  selected,
}: {
  defaults: AgentPlugin[]
  marketplace: AgentMarketplace
  onRepin: (plugin: AgentPlugin) => void
  onServer: (
    marketplace: string,
    plugin: string,
    server: string,
    change: ChangeSetting,
  ) => void
  onToggle: (marketplace: string, plugin: string, on: boolean) => void
  picker: HeaderPicker
  selected: AgentPlugin[]
}) {
  return (
    <Collapsible
      className="group border-tertiary rounded-lg border"
      defaultOpen
    >
      <CollapsibleTrigger className="border-tertiary flex w-full items-center gap-2 px-3 py-2 text-left group-data-[state=open]:border-b">
        <ChevronRight className="text-tertiary size-4 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
        <span className="text-sm font-medium">{marketplace.slug}</span>
        <span className="text-tertiary truncate font-mono text-xs">
          {marketplace.url}
        </span>
        <span className="text-tertiary ml-auto font-mono text-xs">
          {short(marketplace.head_sha) || 'not synced'}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="divide-tertiary divide-y">
          {(marketplace.plugins ?? []).map((plugin) => {
            const defaultPin = defaults.find((d) =>
              same(d, marketplace.slug, plugin.name),
            )
            const isDefault = !!defaultPin
            const chosen = selected.find((p) =>
              same(p, marketplace.slug, plugin.name),
            )
            const pin = defaultPin ?? chosen
            // An external plugin pins its own repository commit.
            const external = plugin.path == null
            const head = external ? plugin.repository_sha : marketplace.head_sha
            const outside = external && !head
            // Hide a plugin that runners cannot load, unless the agent
            // already has it or it is a default (so that its state shows).
            if (outside && !chosen && !isDefault) return null
            const behind =
              !!pin?.sha &&
              !!head &&
              (pin.sha !== head ||
                (external && pin.url !== plugin.repository_url))
            const saved = !!pin?.sha && pin.mcp_servers.length > 0
            const legacy = !!pin?.sha && !saved && plugin.mcp_servers.length > 0
            const repinnable =
              !isDefault && !!chosen && !!head && (behind || legacy)
            return (
              <li
                className="flex items-start gap-3 px-3 py-2"
                key={plugin.name}
              >
                <Checkbox
                  aria-label={plugin.name}
                  checked={isDefault || !!chosen}
                  className="mt-0.5"
                  disabled={isDefault}
                  onCheckedChange={(on) =>
                    onToggle(marketplace.slug, plugin.name, on === true)
                  }
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">{plugin.name}</span>
                    {plugin.version && (
                      <span className="text-tertiary text-xs">
                        {plugin.version}
                      </span>
                    )}
                    {isDefault && <Badge variant="outline">default</Badge>}
                    {outside && (
                      <Badge
                        title="Runners cannot load this source, or the last sync did not resolve its commit"
                        variant="neutral"
                      >
                        unsupported source
                      </Badge>
                    )}
                    {!isDefault && chosen?.sha && (
                      <span className="text-tertiary font-mono text-xs">
                        pinned {short(chosen.sha)}
                      </span>
                    )}
                    {repinnable && chosen && (
                      <button
                        className="text-action text-xs hover:underline"
                        onClick={() => onRepin(chosen)}
                        type="button"
                      >
                        Pin {short(head)}
                      </button>
                    )}
                  </div>
                  {plugin.description && (
                    <p className="text-secondary mt-0.5 text-xs">
                      {plugin.description}
                    </p>
                  )}
                  <PluginServers
                    enabled={isDefault || !!chosen}
                    label={plugin.name}
                    locked={
                      legacy
                        ? isDefault
                          ? 'Secrets need a new pin of this default plugin by the organization.'
                          : 'Pin the plugin again to pick secrets for its servers.'
                        : null
                    }
                    note={
                      !saved && behind
                        ? `Servers at ${short(head)}. This agent runs ${short(pin?.sha)}.`
                        : null
                    }
                    onServer={(server, change) =>
                      onServer(marketplace.slug, plugin.name, server, change)
                    }
                    picker={picker}
                    servers={
                      saved && pin ? pin.mcp_servers : plugin.mcp_servers
                    }
                    settings={chosen?.server_settings ?? {}}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}

function PluginServers({
  enabled,
  label,
  locked,
  note,
  onServer,
  picker,
  servers,
  settings,
}: {
  enabled: boolean
  label: string
  locked: null | string
  note: null | string
  onServer: (server: string, change: ChangeSetting) => void
  picker: HeaderPicker
  servers: CatalogServer[]
  settings: AgentPlugin['server_settings']
}) {
  const names = new Set(servers.map((server) => server.name))
  const gone = Object.keys(settings).filter((name) => !names.has(name))
  if (servers.length === 0 && gone.length === 0) return null
  return (
    <div className="mt-1 flex flex-col gap-0.5">
      {note && <p className="text-tertiary text-xs">{note}</p>}
      {servers.length > 0 && (
        <ul
          aria-label={`MCP servers of ${label}`}
          className="flex flex-col gap-0.5"
        >
          {servers.map((server) => {
            const on = enabled && settings[server.name]?.enabled !== false
            const change = (update: ChangeSetting) =>
              onServer(server.name, update)
            return (
              <li className="flex min-w-0 flex-col gap-1" key={server.name}>
                <div className="flex min-w-0 items-center gap-2 text-xs">
                  <Checkbox
                    aria-label={`${label} MCP server ${server.name}`}
                    checked={on}
                    disabled={!enabled}
                    onCheckedChange={(checked) =>
                      change((setting) => ({
                        ...setting,
                        enabled: checked === true,
                      }))
                    }
                  />
                  <span className="text-tertiary">MCP</span>
                  <span className="text-secondary font-mono">
                    {server.name}
                  </span>
                  <span className="text-tertiary truncate font-mono">
                    {server.url ?? server.type}
                  </span>
                </div>
                <ServerSecrets
                  disabled={!on}
                  label={`${label} ${server.name}`}
                  locked={locked}
                  onChange={change}
                  picker={picker}
                  server={server}
                  setting={settings[server.name]}
                />
              </li>
            )
          })}
        </ul>
      )}
      {gone.length > 0 && (
        <ul
          aria-label={`Settings of MCP servers no longer in ${label}`}
          className="flex flex-col gap-0.5"
        >
          {gone.map((name) => (
            <li className="flex items-center gap-2 text-xs" key={name}>
              <span className="text-secondary font-mono">{name}</span>
              <span className="text-warning">no longer in this plugin</span>
              <button
                aria-label={`Remove the setting of ${name}`}
                className="text-action hover:underline"
                onClick={() => onServer(name, () => DEFAULT_SETTING)}
                type="button"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ServerSecrets({
  disabled,
  label,
  locked,
  onChange,
  picker,
  server,
  setting,
}: {
  disabled: boolean
  label: string
  locked: null | string
  onChange: (change: ChangeSetting) => void
  picker: HeaderPicker
  server: CatalogServer
  setting?: ServerSetting
}) {
  const variables = headerVariables(server)
  const origin = httpsOrigin(server.url)
  const moved = hasSecrets(setting) && setting?.origin !== origin
  if (variables.length === 0 && !moved) return null
  if (locked) return <p className="text-tertiary ml-6 text-xs">{locked}</p>
  return (
    <div className="ml-6 flex flex-col gap-1">
      {moved && (
        <p className="text-warning text-xs">
          The server is now at {server.url ?? server.type}, not at{' '}
          {setting?.origin}. Pick its secrets again.{' '}
          <button
            className="text-action hover:underline"
            onClick={() => onChange((current) => ({ ...current, secrets: {} }))}
            type="button"
          >
            Remove the secrets
          </button>
        </p>
      )}
      {origin
        ? variables.map((variable) => (
            <HeaderSecret
              disabled={disabled || !picker.loaded || picker.isPending}
              key={variable}
              label={`${label} header ${variable}`}
              onChange={(reference) => {
                onChange((current) =>
                  withSecret(current, variable, reference, origin),
                )
                if (reference) picker.grant(reference)
              }}
              picker={picker}
              value={moved ? '' : (setting?.secrets[variable] ?? '')}
              variable={variable}
            />
          ))
        : variables.length > 0 && (
            <p className="text-tertiary text-xs">
              Imbi sends header secrets only to an https URL.
            </p>
          )}
      {origin && variables.length > 0 && picker.missing && (
        <p className="text-tertiary text-xs">{picker.missing}</p>
      )}
    </div>
  )
}
