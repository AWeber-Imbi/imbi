import { useQuery } from '@tanstack/react-query'

import {
  getAgentPlatformConfig,
  listAgentMarketplaces,
  listSecretBindings,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentMarketplace, AgentPlugin } from '@/types'

import type { SettingsDraft } from './agentDraft'
import { Field } from './OverviewTab'

interface PlatformTabProps {
  errors: Record<string, string>
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

const short = (sha?: null | string) => (sha ? sha.slice(0, 7) : '')

/**
 * What the runner gives the agent (ADR 0022): plugins from the
 * marketplaces that the organization allows, the secrets that it may
 * request, and its GitHub App. The organization configuration is the
 * upper limit; the API pins each plugin to a marketplace commit.
 */
export function PlatformTab({
  errors,
  onChange,
  orgSlug,
  value,
}: PlatformTabProps) {
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
  const canReadBindings = useHasPermission('secret_binding:read')
  const bindings = useQuery({
    enabled: canReadBindings,
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
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
            From the marketplaces that the organization allows. A save pins each
            new plugin to the marketplace commit that Imbi synced last.
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
      <div className="grid grid-cols-2 gap-4">
        <Field
          error={errors.secrets}
          help="The secret:// references that the agent may request, one on each line. A grant is still necessary."
          htmlFor="agent-secrets"
          label="Secrets"
        >
          <Textarea
            className="font-mono text-xs"
            id="agent-secrets"
            onChange={(e) => set({ secrets: e.target.value })}
            placeholder="secret://ci/npm_token"
            rows={4}
            value={value.secrets}
          />
        </Field>
        <Field
          error={errors.githubAppBinding}
          help="The secret binding of the agent's own GitHub App."
          htmlFor="agent-github-app"
          label="GitHub App binding"
        >
          <Input
            className="font-mono text-xs"
            id="agent-github-app"
            list="agent-github-app-bindings"
            onChange={(e) => set({ githubAppBinding: e.target.value })}
            placeholder="No GitHub App"
            value={value.githubAppBinding}
          />
          <datalist id="agent-github-app-bindings">
            {(bindings.data ?? []).map((b) => (
              <option key={b.id} value={b.reference} />
            ))}
          </datalist>
        </Field>
      </div>
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
          const outside = plugin.path == null
          const stale =
            chosen?.sha &&
            marketplace.head_sha &&
            chosen.sha !== marketplace.head_sha
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
                      title="Runners load only plugins inside the marketplace repository"
                      variant="neutral"
                    >
                      external source
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
                      Pin {short(marketplace.head_sha)}
                    </button>
                  )}
                </div>
                {plugin.description && (
                  <p className="text-secondary mt-0.5 text-xs">
                    {plugin.description}
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
