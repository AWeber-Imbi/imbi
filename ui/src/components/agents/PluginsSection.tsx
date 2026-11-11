import { useQuery } from '@tanstack/react-query'

import { getAgentPlatformConfig, listAgentMarketplaces } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentMarketplace, AgentPlugin } from '@/types'

import type { SettingsDraft } from './agentDraft'

interface PluginsSectionProps {
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

const short = (sha?: null | string) => (sha ? sha.slice(0, 7) : '')

/**
 * The plugins that the runner loads for the agent (ADR 0022), from the
 * marketplaces that the organization allows. The organization
 * configuration is the upper limit; the API pins each plugin to a
 * marketplace commit. A plugin's MCP servers come with it: while the
 * plugin is on, the agent can use all of their tools.
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
        ? [...value.plugins, { marketplace, plugin }]
        : value.plugins.filter(
            (p) => !(p.marketplace === marketplace && p.plugin === plugin),
          ),
    })
  // A plugin without `sha` is pinned to the newest synced commit.
  const repin = (target: AgentPlugin) =>
    set({
      plugins: value.plugins.map((p) =>
        p === target ? { marketplace: p.marketplace, plugin: p.plugin } : p,
      ),
    })

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
  onToggle,
  selected,
}: {
  defaults: AgentPlugin[]
  marketplace: AgentMarketplace
  onRepin: (plugin: AgentPlugin) => void
  onToggle: (marketplace: string, plugin: string, on: boolean) => void
  selected: AgentPlugin[]
}) {
  return (
    <div className="border-tertiary rounded-lg border">
      <div className="border-tertiary flex items-center gap-2 border-b px-3 py-2">
        <span className="text-sm font-medium">{marketplace.slug}</span>
        <span className="text-tertiary truncate font-mono text-xs">
          {marketplace.url}
        </span>
        <span className="text-tertiary ml-auto font-mono text-xs">
          {short(marketplace.head_sha) || 'not synced'}
        </span>
      </div>
      <ul className="divide-tertiary divide-y">
        {(marketplace.plugins ?? []).map((plugin) => {
          const isDefault = defaults.some(
            (d) =>
              d.marketplace === marketplace.slug && d.plugin === plugin.name,
          )
          const chosen = selected.find(
            (p) =>
              p.marketplace === marketplace.slug && p.plugin === plugin.name,
          )
          // An external plugin pins its own repository commit.
          const external = plugin.path == null
          const head = external ? plugin.repository_sha : marketplace.head_sha
          const outside = external && !head
          const stale =
            chosen?.sha &&
            head &&
            (chosen.sha !== head ||
              (external && chosen.url !== plugin.repository_url))
          return (
            <li className="flex items-start gap-3 px-3 py-2" key={plugin.name}>
              <Checkbox
                aria-label={plugin.name}
                checked={isDefault || !!chosen}
                className="mt-0.5"
                disabled={isDefault || (outside && !chosen)}
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
                  {chosen?.sha && (
                    <span className="text-tertiary font-mono text-xs">
                      pinned {short(chosen.sha)}
                    </span>
                  )}
                  {stale && (
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
                {plugin.mcp_servers.length > 0 && (
                  <p className="text-tertiary mt-0.5 text-xs">
                    MCP {plugin.mcp_servers.length > 1 ? 'servers' : 'server'}:{' '}
                    <span className="font-mono">
                      {plugin.mcp_servers.join(', ')}
                    </span>
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
