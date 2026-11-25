import type { ReactNode } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Bot } from 'lucide-react'

import { listAgentMarketplaces } from '@/api/endpoints'
import { TagChips } from '@/components/tags/TagChip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MarkdownPreview } from '@/components/ui/markdown-editor/MarkdownPreview'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useIcon } from '@/lib/icons'
import { queryKeys } from '@/lib/queryKeys'
import type {
  Agent,
  AgentMarketplace,
  AgentPlugin,
  AgentSettings,
  AgentSubagentRef,
  AgentUsage,
  TicketListItem,
} from '@/types'

import { formatDuration, formatMoney, wordCount } from './agentDraft'
import {
  useAgentToolCatalog,
  useAgentUsage,
  usePromptResolution,
} from './agentQueries'
import { agentsPath, ticketsPath } from './agentsNav'
import { catalogTools, serverOf } from './agentTools'
import {
  capStatus,
  dailyValues,
  daysBetween,
  formatCount,
  formatShare,
  sumTotals,
} from './agentUsage'
import { RunTaskButton } from './RunTaskButton'
import {
  formatCost,
  formatElapsed,
  statusLabel,
  statusVariant,
  TRIGGERS,
} from './taskEvents'
import { useTickets } from './taskQueries'
import { UsageBars } from './UsageBars'
import { useNow } from './useNow'

// The design's runs line: the Dusk label swatch.
const RUNS_COLOR = 'var(--color-entity-project)'

// ponytail: one page of the newest tickets; add paging when an agent
// needs more history than this.
const HISTORY_LIMIT = 100

/** From the run start to the close, or to now while the ticket is open. */
const runDuration = (t: TicketListItem, now: number) =>
  t.run_started_at
    ? formatElapsed(
        (t.closed_at ? Date.parse(t.closed_at) : now) -
          Date.parse(t.run_started_at),
      )
    : '—'

const plural = (count: number, noun: string) =>
  `${count} ${noun}${count === 1 ? '' : 's'}`

export function AgentDetail({ agent }: { agent: Agent }) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('agent:create', agent.organization.slug)
  const canWrite = useHasPermission('agent:write', agent.organization.slug)
  const Icon = useIcon(agent.icon, Bot)
  const prompt = usePromptResolution(agent.prompt_ref)
  const version = prompt.data ?? null
  const settings: Partial<AgentSettings> = agent.settings ?? {}
  const { data: usage } = useAgentUsage(agent.organization.slug, {
    agent_id: agent.id,
  })

  const model = prompt.isLoading
    ? '…'
    : prompt.isError
      ? 'Could not load'
      : (version?.model ?? 'Not set')

  const rows: { mono?: boolean; name: string; value: ReactNode }[] = [
    { name: 'Owner team', value: agent.team?.name ?? '—' },
    { name: 'Author', value: agent.created_by || '—' },
    { mono: true, name: 'Model', value: model },
    { name: 'Slack channel', value: agent.slack_channel || '—' },
    {
      mono: true,
      name: 'Monthly cost cap',
      value: <MonthlyCap agent={agent} usage={usage} />,
    },
    {
      mono: true,
      name: 'Task budget',
      value:
        settings.task_budget == null
          ? 'No budget'
          : formatMoney(settings.task_budget, 6),
    },
    {
      mono: true,
      name: 'Max concurrent tasks',
      value: settings.max_concurrent_tasks ?? 'No limit',
    },
    {
      mono: true,
      name: 'Task timeout',
      value:
        settings.task_timeout_seconds == null
          ? 'No limit'
          : formatDuration(settings.task_timeout_seconds),
    },
    {
      mono: true,
      name: 'Runner labels',
      value: settings.required_labels?.join(', ') || 'Any runner',
    },
    {
      mono: true,
      name: 'Egress destinations',
      value: settings.egress_destinations?.join(', ') || 'None',
    },
    {
      name: 'Human response SLA',
      value: settings.response_sla ?? 'Not set',
    },
    {
      mono: true,
      name: 'Runs (30 days)',
      value: usage ? formatCount(sumTotals(usage.agents).tasks) : '—',
    },
    { name: 'Tags', value: <TagChips tags={agent.tags} /> },
  ]

  const system = version?.system ?? ''

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <Button
          onClick={() => navigate(agentsPath('manage'))}
          size="sm"
          variant="outline"
        >
          <ArrowLeft className="mr-2 size-4" />
          Back to agents
        </Button>
      </div>

      <div className="flex items-start gap-4">
        <div className="bg-secondary text-action flex size-12 shrink-0 items-center justify-center rounded-lg">
          <Icon className="size-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h2 className="text-h2">{agent.name}</h2>
            <Badge variant={agent.enabled ? 'success' : 'neutral'}>
              {agent.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
            <span className="text-tertiary font-mono text-sm tabular-nums">
              v{agent.version}
            </span>
          </div>
          {agent.description && (
            <p className="text-secondary mt-1 text-sm text-pretty">
              {agent.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <RunTaskButton agent={agent} />
          {canCreate && (
            <Button
              onClick={() =>
                navigate(
                  `${agentsPath('manage', 'new')}?from=${encodeURIComponent(agent.slug)}`,
                )
              }
              size="sm"
              variant="outline"
            >
              Duplicate
            </Button>
          )}
          {canWrite && (
            <Button
              onClick={() => navigate(agentsPath('manage', agent.slug, 'edit'))}
              size="sm"
            >
              Edit
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="mb-6">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="prompt">System prompt</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent className="flex flex-col gap-6" value="overview">
          <div className="border-border bg-card rounded-lg border">
            <dl className="grid grid-cols-3 gap-x-8 gap-y-5 p-6">
              {rows.map((row) => (
                <div className="flex flex-col gap-1" key={row.name}>
                  <dt className="text-overline text-tertiary uppercase">
                    {row.name}
                  </dt>
                  <dd className={row.mono ? 'font-mono text-sm' : 'text-sm'}>
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>

          {usage && <CostOverTime usage={usage} />}

          <div className="grid grid-cols-2 items-start gap-6">
            <ToolAccessCard agent={agent} />
            <SubagentsCard agent={agent} />
          </div>
        </TabsContent>

        <TabsContent value="prompt">
          <div className="border-border bg-card rounded-lg border">
            <div className="border-border flex items-center justify-between border-b px-6 py-4">
              <h3 className="text-card-title">System prompt</h3>
              {system && (
                <span className="text-tertiary font-mono text-sm tabular-nums">
                  {wordCount(system).toLocaleString()} words
                </span>
              )}
            </div>
            <div aria-label="System prompt" className="px-6 py-4" role="region">
              {prompt.isLoading ? (
                <p className="text-tertiary text-sm">Loading…</p>
              ) : system ? (
                <MarkdownPreview value={system} />
              ) : (
                <p className="text-tertiary text-sm">
                  {prompt.isError
                    ? 'Could not load the system prompt.'
                    : 'No system prompt yet.'}
                </p>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="history">
          <HistoryCard agent={agent} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

/** Daily cost bars and a runs line over the last 30 days. */
function CostOverTime({ usage }: { usage: AgentUsage }) {
  const days = daysBetween(usage.start, usage.end)
  const cost = dailyValues(usage, (row) => Number(row.cost))
  const runs = dailyValues(usage, (row) => row.tasks)
  const total = sumTotals(usage.agents)
  const stats = [
    { label: 'Total', value: formatMoney(total.cost) },
    { label: 'Daily avg', value: formatMoney(total.cost / days.length) },
    {
      label: 'Avg / run',
      value: total.tasks > 0 ? formatMoney(total.cost / total.tasks) : '—',
    },
    { label: 'Peak day', value: formatMoney(Math.max(...cost)) },
  ]
  return (
    <div className="border-border bg-card rounded-lg border">
      <div className="border-border flex items-end justify-between border-b px-6 py-4">
        <div>
          <h3 className="text-card-title">Cost over time</h3>
          <p className="text-tertiary text-xs">Daily spend · last 30 days</p>
        </div>
        <div className="flex items-center gap-6">
          {stats.map((s) => (
            <span className="flex flex-col text-right" key={s.label}>
              <span className="text-overline text-tertiary uppercase">
                {s.label}
              </span>
              <span className="font-mono text-sm tabular-nums">{s.value}</span>
            </span>
          ))}
        </div>
      </div>
      {usage.days.length === 0 ? (
        <p className="text-tertiary px-6 py-10 text-center text-sm">
          No spend in the last 30 days.
        </p>
      ) : (
        <>
          <div className="px-6 py-5">
            <UsageBars
              days={days}
              format={(n) => formatMoney(n)}
              height={180}
              label="Cost and runs per day"
              line={{ color: RUNS_COLOR, values: runs }}
              series={[
                { color: 'var(--ds-action-bg)', key: 'cost', values: cost },
              ]}
            />
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 px-6 pb-4">
            <span className="text-secondary flex items-center gap-2 text-xs">
              <span className="bg-action size-2.25 rounded-xs" />
              Cost per day
            </span>
            <span className="text-secondary flex items-center gap-2 text-xs">
              <span
                className="h-0.5 w-3 rounded-xs"
                style={{ background: RUNS_COLOR }}
              />
              Runs per day
            </span>
          </div>
        </>
      )}
    </div>
  )
}

/** The tickets that this agent worked on, newest first. */
function HistoryCard({ agent }: { agent: Agent }) {
  const orgSlug = agent.organization.slug
  const params = { agent_id: [agent.id], limit: HISTORY_LIMIT }
  const tickets = useTickets(orgSlug, params)
  const rows = tickets.data ?? []
  const now = useNow(rows.some((t) => t.run_started_at && !t.closed_at))
  const message = tickets.isLoading
    ? 'Loading…'
    : tickets.isError
      ? 'Could not load the history.'
      : rows.length === 0
        ? 'This agent has not worked on a ticket yet.'
        : null
  return (
    <div className="border-border bg-card overflow-hidden rounded-lg border">
      {message ? (
        <p className="text-tertiary px-6 py-5 text-sm">{message}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="text-overline uppercase">
              <TableHead className="px-6">Ticket</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Duration</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="px-6">Trigger</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="px-6 font-mono whitespace-nowrap">
                  <Link
                    className="text-action hover:underline"
                    to={ticketsPath(orgSlug, t.short_id)}
                  >
                    {t.short_id}
                  </Link>
                </TableCell>
                <TableCell className="max-w-0 truncate" title={t.title}>
                  {t.title}
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(t)}>{statusLabel(t)}</Badge>
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {runDuration(t, now)}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {formatCost(Number(t.cost_total))}
                </TableCell>
                <TableCell className="text-secondary px-6 whitespace-nowrap">
                  {TRIGGERS[t.origin.kind].label}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

/**
 * The spend of this UTC month against the advisory monthly cost cap,
 * with a warning from 80% of the cap.
 */
function MonthlyCap({
  agent,
  usage,
}: {
  agent: Agent
  usage: AgentUsage | undefined
}) {
  const raw = agent.settings?.monthly_cost_cap
  if (raw == null) return 'No cap'
  if (!usage) return formatMoney(raw)
  const spent = Number(usage.month_to_date[agent.id] ?? 0)
  const status = capStatus(agent, spent)
  return (
    <span className="flex items-center gap-2">
      {formatMoney(spent)} of {formatMoney(raw)}
      {status && (
        <Badge variant={status.level === 'over' ? 'danger' : 'warning'}>
          {formatShare(status.share)} of cap
        </Badge>
      )}
    </span>
  )
}

/** A plugin, with every tool of the MCP servers that it brings. */
function PluginRow({
  plugin,
  servers,
}: {
  plugin: AgentPlugin
  servers: string[]
}) {
  return (
    <div className="border-border flex items-center gap-4 border-b px-6 py-3 last:border-b-0">
      <span className="w-30 shrink-0 truncate text-sm font-medium">
        {plugin.plugin}
      </span>
      <span className="text-secondary min-w-0 flex-1 truncate font-mono text-xs">
        {servers.length > 0 && `MCP: ${servers.join(', ')}`}
      </span>
      <span className="text-tertiary shrink-0 font-mono text-xs">
        {plugin.marketplace}
        {plugin.sha && ` @ ${plugin.sha.slice(0, 7)}`}
      </span>
    </div>
  )
}

/** The MCP servers that a plugin brings, from the marketplace catalog. */
function pluginServers(
  marketplaces: AgentMarketplace[],
  plugin: AgentPlugin,
): string[] {
  const servers =
    marketplaces
      .find((m) => m.slug === plugin.marketplace)
      ?.plugins?.find((p) => p.name === plugin.plugin)?.mcp_servers ?? []
  return servers.map((server) => server.name)
}

function SubagentItem({ subagent }: { subagent: AgentSubagentRef }) {
  const Icon = useIcon(subagent.icon, Bot)
  const tools = `${subagent.tool_count} tool${subagent.tool_count === 1 ? '' : 's'}`
  return (
    <div className="border-border flex items-center gap-3 border-b px-6 py-3 last:border-b-0">
      <Icon className="text-secondary size-4 shrink-0" />
      <span className="text-sm font-medium">{subagent.name}</span>
      <span className="text-tertiary flex-1 text-right font-mono text-xs tabular-nums">
        v{subagent.version} · {tools}
      </span>
    </div>
  )
}

/** The agents that this agent delegates to, in order. */
function SubagentsCard({ agent }: { agent: Agent }) {
  const subagents = agent.subagents ?? []
  return (
    <div className="border-border bg-card rounded-lg border">
      <div className="border-border flex items-center justify-between border-b px-6 py-4">
        <h3 className="text-card-title">Subagents</h3>
        <span className="text-tertiary font-mono text-sm tabular-nums">
          {subagents.length}
        </span>
      </div>
      <div className="flex flex-col">
        {subagents.length === 0 && (
          <p className="text-tertiary px-6 py-5 text-sm">
            No subagents. This agent does all of its own work.
          </p>
        )}
        {subagents.map((s) => (
          <SubagentItem key={s.agent_id} subagent={s} />
        ))}
      </div>
    </div>
  )
}

/** The enabled plugins and tools, one row for each plugin and server. */
function ToolAccessCard({ agent }: { agent: Agent }) {
  const orgSlug = agent.organization.slug
  const { query: catalog } = useAgentToolCatalog(orgSlug)
  const marketplaces = useQuery({
    queryFn: ({ signal }) => listAgentMarketplaces(orgSlug, signal),
    queryKey: queryKeys.agentMarketplaces(orgSlug),
  })
  const plugins = agent.settings?.plugins ?? []
  const keys = Object.keys(agent.tools ?? {}).sort()
  const total = catalog.data ? catalogTools(catalog.data).length : 0
  const servers = new Map<string, string[]>()
  for (const key of keys) {
    const server = serverOf(key)
    servers.set(server, [
      ...(servers.get(server) ?? []),
      key.slice(server.length + 1),
    ])
  }
  const toolCount = catalog.data
    ? `${keys.length} of ${total} enabled`
    : `${keys.length} enabled`
  return (
    <div className="border-border bg-card rounded-lg border">
      <div className="border-border flex items-center justify-between border-b px-6 py-4">
        <h3 className="text-card-title">Tools and MCP access</h3>
        <span className="text-tertiary font-mono text-sm tabular-nums">
          {plugins.length > 0
            ? `${plural(plugins.length, 'plugin')} · ${toolCount}`
            : toolCount}
        </span>
      </div>
      <div className="flex flex-col">
        {keys.length === 0 && plugins.length === 0 && (
          <p className="text-tertiary px-6 py-4 text-sm">No tools enabled.</p>
        )}
        {plugins.map((plugin) => (
          <PluginRow
            key={`${plugin.marketplace}/${plugin.plugin}`}
            plugin={plugin}
            servers={pluginServers(marketplaces.data ?? [], plugin)}
          />
        ))}
        {[...servers].map(([server, tools]) => (
          <div
            className="border-border flex items-center gap-4 border-b px-6 py-3 last:border-b-0"
            key={server}
          >
            <span className="w-30 shrink-0 truncate text-sm font-medium">
              {server}
            </span>
            <span
              className="text-secondary min-w-0 flex-1 truncate font-mono text-xs"
              title={tools.join(', ')}
            >
              {tools.join(', ')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
