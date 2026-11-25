import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'

import { getAgentPlatformConfig, listAgentMarketplaces } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { ErrorBanner } from '@/components/ui/error-banner'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentMarketplace, AgentPlugin, CatalogServer } from '@/types'

import type { SettingsDraft } from './agentDraft'

interface PluginsSectionProps {
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
  const setServer = (
    marketplace: string,
    plugin: string,
    server: string,
    on: boolean,
  ) => {
    const current = value.plugins.find((p) => same(p, marketplace, plugin))
    const { [server]: _removed, ...rest } = current?.server_settings ?? {}
    const settings = on ? rest : { ...rest, [server]: { enabled: false } }
    const isDefault = defaults.some((d) => same(d, marketplace, plugin))
    if (!current) {
      set({
        plugins: [...value.plugins, entry(marketplace, plugin, settings)],
      })
    } else if (isDefault && Object.keys(settings).length === 0) {
      set({ plugins: value.plugins.filter((p) => p !== current) })
    } else {
      set({
        plugins: value.plugins.map((p) =>
          p === current ? { ...p, server_settings: settings } : p,
        ),
      })
    }
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
            each new plugin to the commit that Imbi synced last.
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
            onServer={setServer}
            onToggle={toggle}
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

function MarketplacePlugins({
  defaults,
  marketplace,
  onRepin,
  onServer,
  onToggle,
  selected,
}: {
  defaults: AgentPlugin[]
  marketplace: AgentMarketplace
  onRepin: (plugin: AgentPlugin) => void
  onServer: (
    marketplace: string,
    plugin: string,
    server: string,
    on: boolean,
  ) => void
  onToggle: (marketplace: string, plugin: string, on: boolean) => void
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
            const stale = !isDefault && behind
            const saved = !!pin?.sha && pin.mcp_servers.length > 0
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
                    {stale && chosen && (
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
                    note={
                      !saved && behind
                        ? `Servers at ${short(head)}. This agent runs ${short(pin?.sha)}.`
                        : null
                    }
                    onServer={(server, on) =>
                      onServer(marketplace.slug, plugin.name, server, on)
                    }
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
  note,
  onServer,
  servers,
  settings,
}: {
  enabled: boolean
  label: string
  note: null | string
  onServer: (server: string, on: boolean) => void
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
          {servers.map((server) => (
            <li
              className="flex min-w-0 items-center gap-2 text-xs"
              key={server.name}
            >
              <Checkbox
                aria-label={`${label} MCP server ${server.name}`}
                checked={enabled && settings[server.name]?.enabled !== false}
                disabled={!enabled}
                onCheckedChange={(on) => onServer(server.name, on === true)}
              />
              <span className="text-tertiary">MCP</span>
              <span className="text-secondary font-mono">{server.name}</span>
              <span className="text-tertiary truncate font-mono">
                {server.url ?? server.type}
              </span>
            </li>
          ))}
        </ul>
      )}
      {gone.length > 0 && (
        <ul
          aria-label={`Turned-off MCP servers no longer in ${label}`}
          className="flex flex-col gap-0.5"
        >
          {gone.map((name) => (
            <li className="flex items-center gap-2 text-xs" key={name}>
              <span className="text-secondary font-mono">{name}</span>
              <span className="text-warning">no longer in this plugin</span>
              <button
                aria-label={`Remove the setting of ${name}`}
                className="text-action hover:underline"
                onClick={() => onServer(name, true)}
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
