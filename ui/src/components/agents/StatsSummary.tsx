import { Bot } from 'lucide-react'

import { cn } from '@/lib/utils'

import type { StatsRanked, TaskStatistics } from './statsModel'
import { formatCost, formatElapsed, formatTokens } from './taskEvents'
import { formatDuration } from './trajectoryModel'

interface Part {
  color: string
  label: string
  text: string
  value: number
}

export function money(cost: number): string {
  return cost > 0 ? formatCost(cost) : '—'
}

export function StatsSummary({
  onReveal,
  stats,
}: {
  onReveal: (item: StatsRanked) => void
  stats: TaskStatistics
}) {
  const { breakdown: b, totals } = stats
  const tokens =
    totals.input + totals.cacheRead + totals.cacheWrite + totals.output
  const turns = totals.turns > 1
  return (
    <div className="border-b">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(13rem,1fr))] gap-x-8 gap-y-5 px-4 pt-4 pb-5">
        <Figure
          label="Time"
          parts={[
            part('bg-(--tj-span-assistant)', 'Model', b.time.model, time),
            part('bg-(--tj-span-subtool)', 'Subagents', b.time.subagents, time),
            part('bg-(--tj-span-tool)', 'Tools', b.time.tools, time),
            part('bg-(--tj-border-2)', 'Other', b.time.other, time),
            part('bg-(--tj-border-1)', 'Idle', b.time.idle, time),
          ]}
          title="From the ticket's creation to its close. Idle is the time no turn was running. Subagents count once while they run at the same time, and Tools only while no subagent runs."
          value={time((totals.totalMs ?? 0) + b.time.idle)}
        />
        <Figure
          label="Cost"
          parts={[
            part('bg-(--tj-span-assistant)', 'Main agent', b.cost.main, money),
            part(
              'bg-(--tj-span-subtool)',
              'Subagents',
              b.cost.subagents,
              money,
            ),
          ]}
          value={money(totals.cost)}
        />
        <Figure
          label="Tokens"
          parts={[
            part(
              'bg-(--tj-span-context)',
              'Cache read',
              totals.cacheRead,
              formatTokens,
            ),
            part(
              'bg-(--tj-span-tool)',
              'Cache write',
              totals.cacheWrite,
              formatTokens,
            ),
            part('bg-(--tj-span-user)', 'Uncached', totals.input, formatTokens),
            part(
              'bg-(--tj-span-assistant)',
              'Output',
              totals.output,
              formatTokens,
            ),
          ]}
          title="Every token of the task, subagents included"
          value={formatTokens(tokens)}
        />
        <ContextFigure points={b.context.map((c) => c.value)} />
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(20rem,1fr))] gap-x-8 gap-y-5 px-4 pb-4">
        <Ranking
          format={money}
          items={stats.costliest}
          onReveal={onReveal}
          title="Most expensive"
          total={totals.cost}
          turns={turns}
        />
        <Ranking
          format={time}
          items={stats.slowest}
          onReveal={onReveal}
          title="Slowest"
          total={(totals.totalMs ?? 0) + b.time.idle}
          turns={turns}
        />
      </div>
    </div>
  )
}

export function time(ms: null | number): string {
  if (ms === null) return '—'
  return ms < 60_000 ? formatDuration(ms) : formatElapsed(ms)
}

function ContextFigure({ points }: { points: number[] }) {
  if (!points.length) return null
  const peak = Math.max(...points)
  const first = points[0]
  const last = points[points.length - 1]
  const line = points
    .map(
      (v, i) =>
        `${points.length > 1 ? i / (points.length - 1) : 0.5},${1 - v / peak}`,
    )
    .join(' ')
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span
        className="text-tertiary text-xs"
        title="The main agent's prompt size at each step"
      >
        Context
      </span>
      <span className="text-lg leading-none font-medium tabular-nums">
        {formatTokens(peak)}{' '}
        <span className="text-tertiary text-xs font-normal">peak</span>
      </span>
      <svg
        aria-hidden
        className="h-5 w-full overflow-visible"
        preserveAspectRatio="none"
        viewBox="0 0 1 1"
      >
        <polyline
          fill="none"
          points={line}
          stroke="var(--tj-span-assistant)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="text-secondary text-xs tabular-nums">
        {formatTokens(first)} → {formatTokens(last)} over{' '}
        {points.length === 1 ? '1 step' : `${points.length} steps`}
      </span>
    </div>
  )
}

function Figure({
  label,
  parts,
  title,
  value,
}: {
  label: string
  parts: Part[]
  title?: string
  value: string
}) {
  const shown = parts.filter((p) => p.value > 0)
  const sum = shown.reduce((n, p) => n + p.value, 0)
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-tertiary text-xs" title={title}>
        {label}
      </span>
      <span className="text-lg leading-none font-medium tabular-nums">
        {value}
      </span>
      <div className="flex h-1.5 gap-px overflow-hidden rounded-full bg-(--tj-border-2)">
        {sum > 0 &&
          shown.map((p) => (
            <div
              className={p.color}
              key={p.label}
              style={{ width: `${(p.value / sum) * 100}%` }}
              title={`${p.label} ${p.text}`}
            />
          ))}
      </div>
      <ul className="text-secondary flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums">
        {shown.map((p) => (
          <li className="flex items-center gap-1" key={p.label}>
            <span className={cn('size-1.5 rounded-full', p.color)} />
            {p.label} {p.text}
          </li>
        ))}
      </ul>
    </div>
  )
}

function part(
  color: string,
  label: string,
  value: number,
  format: (n: number) => string,
): Part {
  return { color, label, text: format(value), value }
}

function Ranking({
  format,
  items,
  onReveal,
  title,
  total,
  turns,
}: {
  format: (n: number) => string
  items: StatsRanked[]
  onReveal: (item: StatsRanked) => void
  title: string
  total: number
  turns: boolean
}) {
  if (!items.length) return null
  const top = items[0].value
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-tertiary text-xs">{title}</span>
      <ol className="flex flex-col">
        {items.map((item) => {
          const where = `${turns ? `Turn ${item.turn}, ` : ''}Step ${item.step}`
          return (
            <li key={`${item.turn}:${item.step}:${item.subagent ?? ''}`}>
              <button
                className="hover:bg-secondary focus-visible:bg-secondary -mx-1.5 grid w-[calc(100%+(--spacing(3)))] grid-cols-[minmax(0,1fr)_3rem_6rem] items-center gap-3 rounded-sm px-1.5 py-1 text-left text-sm outline-none"
                onClick={() => onReveal(item)}
                title={`${where}: show in the table`}
                type="button"
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  {item.subagent ? (
                    <Bot className="text-tertiary size-3.5 shrink-0" />
                  ) : (
                    <span className="text-tertiary shrink-0 text-xs tabular-nums">
                      {where}
                    </span>
                  )}
                  <span className="truncate">{item.label}</span>
                </span>
                <span className="h-1 overflow-hidden rounded-full bg-(--tj-border-2)">
                  <span
                    className={cn(
                      'block h-full rounded-full',
                      item.subagent
                        ? 'bg-(--tj-span-subtool)'
                        : 'bg-(--tj-span-assistant)',
                    )}
                    style={{ width: `${(item.value / top) * 100}%` }}
                  />
                </span>
                <span className="text-right tabular-nums">
                  {format(item.value)}
                  {total > 0 && (
                    <span className="text-tertiary ml-1 text-xs">
                      {Math.round((item.value / total) * 100)}%
                    </span>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
