import { useState } from 'react'

import { Alert } from '@/components/ui/alert'
import { ErrorBanner } from '@/components/ui/error-banner'
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { LABEL_SWATCHES } from '@/lib/chip-colors'
import type { Agent, AgentUsage, AgentUsageTotals } from '@/types'

import { formatMoney } from './agentDraft'
import { useAgentList, useAgentUsage } from './agentQueries'
import {
  cacheHit,
  capStatus,
  dailyValues,
  daysBetween,
  formatCount,
  formatShare,
  inputTokens,
  sumTotals,
} from './agentUsage'
import { UsageBars } from './UsageBars'

const ALL = 'all'
const RANGES = ['7', '30', '90']
const swatch = (name: string) =>
  LABEL_SWATCHES.find((s) => s.name === name)?.hex ?? ''
// The design's order: amber first, then Dusk, Clay, and Moss.
const SERIES_COLORS = [
  'var(--ds-action-bg)',
  swatch('Dusk'),
  swatch('Clay'),
  swatch('Moss'),
]
const OTHER_COLOR = 'var(--ds-text-tertiary)'
const OTHER = 'other'

type Metric = 'cost' | 'tokens'

const metricOf: Record<Metric, (t: AgentUsageTotals) => number> = {
  cost: (t) => Number(t.cost),
  tokens: (t) => inputTokens(t) + t.tokens_out,
}

interface FocusProps {
  focus: null | string
  nameOf: (id: string) => string
  onFocus: (key: null | string) => void
  usage: AgentUsage
}

/** Token use and cost of the agents of the org, by day and by agent. */
export function UsagePage() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('agent_task:read')
  const [range, setRange] = useState('30')
  const [agentId, setAgentId] = useState(ALL)
  const [metric, setMetric] = useState<Metric>('cost')
  const [focus, setFocus] = useState<null | string>(null)
  const { data: agents = [] } = useAgentList(orgSlug)
  const usage = useAgentUsage(orgSlug, {
    agent_id: agentId === ALL ? undefined : agentId,
    start: daysAgo(Number(range) - 1),
  })
  const names = new Map(agents.map((a) => [a.id, a.name]))
  const nameOf = (id: string) => names.get(id) ?? id

  if (!canRead) {
    return (
      <div className="p-8">
        <Alert>You need the agent_task:read permission to see usage.</Alert>
      </div>
    )
  }

  const reset = () => {
    setRange('30')
    setAgentId(ALL)
    setFocus(null)
  }

  return (
    <div className="flex flex-col gap-4 p-8">
      <div className="flex flex-wrap items-center gap-2">
        <Select onValueChange={setRange} value={range}>
          <SelectTrigger aria-label="Range" className="h-8 w-auto text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RANGES.map((r) => (
              <SelectItem key={r} value={r}>
                Last {r} days
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          onValueChange={(v) => {
            setAgentId(v)
            setFocus(null)
          }}
          value={agentId}
        >
          <SelectTrigger aria-label="Agent" className="h-8 w-auto text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All agents</SelectItem>
            {agents.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          className="text-action ml-1 text-xs hover:underline"
          onClick={reset}
          type="button"
        >
          Reset
        </button>
      </div>

      {usage.error ? (
        <ErrorBanner error={usage.error} title="Failed to load usage" />
      ) : !usage.data ? (
        <p className="text-tertiary text-sm">Loading…</p>
      ) : (
        <>
          <CapWarnings agents={agents} usage={usage.data} />
          <UsageTotals usage={usage.data} />
          <UsageChart
            focus={focus}
            metric={metric}
            nameOf={nameOf}
            onFocus={setFocus}
            onMetric={setMetric}
            usage={usage.data}
          />
          <UsageTable
            focus={focus}
            nameOf={nameOf}
            onFocus={setFocus}
            range={range}
            usage={usage.data}
          />
        </>
      )}
    </div>
  )
}

/** Agents at 80% or more of their advisory monthly cost cap. */
function CapWarnings({
  agents,
  usage,
}: {
  agents: Agent[]
  usage: AgentUsage
}) {
  const rows = agents.flatMap((a) => {
    const status = capStatus(a, Number(usage.month_to_date[a.id] ?? 0))
    return status ? [{ agent: a, status }] : []
  })
  if (rows.length === 0) return null
  const over = rows.some((r) => r.status.level === 'over')
  return (
    <Alert title="Monthly cost cap" variant={over ? 'danger' : 'warning'}>
      <ul>
        {rows.map(({ agent, status }) => (
          <li key={agent.id}>
            {agent.name} spent {formatMoney(status.spent)} of{' '}
            {formatMoney(status.cap)} this month ({formatShare(status.share)}
            ).
          </li>
        ))}
      </ul>
      <p className="mt-1 text-xs">
        The cap is advisory. Agents continue to run.
      </p>
    </Alert>
  )
}

/** The chart series: the top four agents by cost, then the rest. */
function chartSeries(agents: AgentUsageTotals[]) {
  const top = agents.length > 5 ? agents.slice(0, 4) : agents
  const series = top.map((a, i) => ({
    color: SERIES_COLORS[i],
    ids: [a.agent_id],
    key: a.agent_id,
  }))
  if (top.length < agents.length) {
    series.push({
      color: OTHER_COLOR,
      ids: agents.slice(4).map((a) => a.agent_id),
      key: OTHER,
    })
  }
  return series
}

function daysAgo(n: number): string {
  const day = new Date()
  day.setUTCDate(day.getUTCDate() - n)
  return day.toISOString().slice(0, 10)
}

function UsageChart({
  focus,
  metric,
  nameOf,
  onFocus,
  onMetric,
  usage,
}: FocusProps & { metric: Metric; onMetric: (m: Metric) => void }) {
  const days = daysBetween(usage.start, usage.end)
  const all = chartSeries(usage.agents)
  const shown = all
    .filter((s) => !focus || s.key === focus)
    .map((s) => ({
      ...s,
      values: dailyValues(usage, metricOf[metric], new Set(s.ids)),
    }))
  const format =
    metric === 'cost'
      ? (n: number) => formatMoney(n)
      : (n: number) => formatCount(Math.round(n))
  const totals = days.map((_, i) => shown.reduce((n, s) => n + s.values[i], 0))
  const label = (key: string) => (key === OTHER ? 'Other agents' : nameOf(key))

  return (
    <div className="border-border bg-card rounded-lg border">
      <div className="border-border flex items-end justify-between border-b px-5 py-4">
        <SegmentedControl
          ariaLabel="Chart metric"
          onValueChange={(v) => onMetric(v as Metric)}
          value={metric}
        >
          <SegmentedControlItem value="cost">Cost</SegmentedControlItem>
          <SegmentedControlItem value="tokens">
            Token usage
          </SegmentedControlItem>
        </SegmentedControl>
        <span className="text-tertiary flex items-center gap-4 font-mono text-xs tabular-nums">
          <span>
            by agent · {metric === 'cost' ? 'dollars' : 'tokens'} per day
          </span>
          <span>peak {format(Math.max(0, ...totals))}</span>
        </span>
      </div>
      {usage.agents.length === 0 ? (
        <p className="text-tertiary px-5 py-10 text-center text-sm">
          No usage in this range.
        </p>
      ) : (
        <>
          <div className="px-5 pt-5">
            <UsageBars
              days={days}
              format={format}
              label={`${metric === 'cost' ? 'Cost' : 'Tokens'} per day by agent`}
              series={shown}
            />
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 px-5 py-4">
            {all.map((s) => (
              <button
                className={`flex items-center gap-2 text-xs ${!focus || focus === s.key ? 'text-secondary' : 'text-tertiary opacity-40'}`}
                key={s.key}
                onClick={() => onFocus(focus === s.key ? null : s.key)}
                type="button"
              >
                <span
                  className="size-2.25 rounded-xs"
                  style={{ background: s.color }}
                />
                {label(s.key)}
              </button>
            ))}
            {focus && (
              <span className="text-tertiary ml-auto text-xs">
                Showing {label(focus)} only. Click again to show all.
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function UsageTable({
  focus,
  nameOf,
  onFocus,
  range,
  usage,
}: FocusProps & { range: string }) {
  const series = chartSeries(usage.agents)
  const colorOf = (id: string) =>
    series.find((s) => s.ids.includes(id))?.color ?? OTHER_COLOR
  const keyOf = (id: string) => series.find((s) => s.ids.includes(id))?.key
  const total = sumTotals(usage.agents)
  const cell = 'px-5 py-2.5 text-right font-mono text-sm tabular-nums'
  const head = 'text-overline text-tertiary px-5 py-2.5 text-right uppercase'

  return (
    <div className="border-border bg-card overflow-hidden rounded-lg border">
      <div className="border-border flex items-center justify-between border-b px-5 py-4">
        <h3 className="text-card-title">Usage by agent</h3>
        <span className="text-tertiary text-xs">
          Grouped by agent · last {range} days
        </span>
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-border border-b">
            <th className={`${head} text-left`}>Agent</th>
            <th className={head}>Tasks</th>
            <th className={head}>Tokens in</th>
            <th className={head}>Tokens out</th>
            <th className={head}>Cache hit</th>
            <th className={head}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {usage.agents.map((row) => {
            const key = keyOf(row.agent_id) ?? row.agent_id
            return (
              <tr
                className={`border-border hover:bg-secondary cursor-pointer border-b ${focus && focus !== key ? 'opacity-45' : ''} ${focus === key ? 'bg-secondary' : ''}`}
                key={row.agent_id}
                onClick={() => onFocus(focus === key ? null : key)}
              >
                <td className="px-5 py-2.5">
                  <span className="flex items-center gap-2">
                    <span
                      className="size-2.25 rounded-xs"
                      style={{ background: colorOf(row.agent_id) }}
                    />
                    <span className="text-sm font-medium">
                      {nameOf(row.agent_id)}
                    </span>
                  </span>
                </td>
                <td className={cell}>{formatCount(row.tasks)}</td>
                <td className={cell}>{formatCount(inputTokens(row))}</td>
                <td className={cell}>{formatCount(row.tokens_out)}</td>
                <td className={`${cell} text-secondary`}>
                  {formatShare(cacheHit(row))}
                </td>
                <td className={cell}>{formatMoney(row.cost)}</td>
              </tr>
            )
          })}
          <tr className="bg-secondary">
            <td className="px-5 py-2.5 text-sm font-semibold">Total</td>
            <td className={`${cell} font-semibold`}>
              {formatCount(total.tasks)}
            </td>
            <td className={`${cell} font-semibold`}>
              {formatCount(inputTokens(total))}
            </td>
            <td className={`${cell} font-semibold`}>
              {formatCount(total.tokens_out)}
            </td>
            <td className={`${cell} text-secondary`}>
              {formatShare(cacheHit(total))}
            </td>
            <td className={`${cell} font-semibold`}>
              {formatMoney(total.cost)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function UsageTotals({ usage }: { usage: AgentUsage }) {
  const total = sumTotals(usage.agents)
  const tiles = [
    {
      label: 'Tokens in',
      note: 'includes cached reads',
      value: formatCount(inputTokens(total)),
    },
    {
      label: 'Tokens out',
      note: 'billed at the output rate',
      value: formatCount(total.tokens_out),
    },
    {
      label: 'Spend',
      note: `${formatCount(total.tasks)} task${total.tasks === 1 ? '' : 's'}`,
      value: formatMoney(total.cost),
    },
  ]
  return (
    <div className="grid grid-cols-3 gap-4">
      {tiles.map((t) => (
        <div
          className="border-border bg-card flex flex-col gap-1 rounded-lg border px-5 py-4"
          key={t.label}
        >
          <span className="text-secondary text-xs">{t.label}</span>
          <span className="font-mono text-2xl tracking-tight tabular-nums">
            {t.value}
          </span>
          <span className="text-tertiary text-xs">{t.note}</span>
        </div>
      ))}
    </div>
  )
}
