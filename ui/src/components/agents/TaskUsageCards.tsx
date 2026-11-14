import { Fragment, type ReactNode, useMemo } from 'react'

import { Clock, Coins } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

import { formatMoney } from './agentDraft'
import { formatElapsed, formatTokens } from './taskEvents'
import { taskActivity, taskUsage } from './taskStats'
import { buildTrajectory, formatDuration } from './trajectoryModel'

type Row = [label: string, value: string]

export function TaskActivityCard({
  elapsedMs,
  events,
  task,
}: {
  elapsedMs: number
  events: AgentTaskEvent[]
  task: AgentTask
}) {
  const live = task.status !== 'closed'
  const activity = useMemo(
    () => taskActivity(buildTrajectory(events, live), task.tokens_out),
    [events, live, task.tokens_out],
  )
  const rows: Row[] = [
    ['Turns', String(activity.turns)],
    ['Model requests', String(activity.requests)],
    [
      'Tool calls',
      activity.failedCalls
        ? `${activity.toolCalls} (${activity.failedCalls} failed)`
        : String(activity.toolCalls),
    ],
    ['Model time', time(activity.modelMs)],
    ['Tool time', time(activity.toolMs)],
  ]
  if (activity.outputPerSecond !== null)
    rows.push(['Output speed', speed(activity.outputPerSecond)])
  return (
    <StatCard
      icon={<Clock className="size-3.5" />}
      label={`Elapsed ${formatElapsed(elapsedMs)}`}
      trigger={<span className="text-xs">{formatElapsed(elapsedMs)}</span>}
    >
      <Section>
        <p className="text-foreground font-medium">Activity</p>
      </Section>
      <Section>
        <Rows rows={rows} />
      </Section>
    </StatCard>
  )
}

export function TaskUsageCard({
  events,
  task,
}: {
  events: AgentTaskEvent[]
  task: AgentTask
}) {
  const models = useMemo(() => taskUsage(events).models, [events])
  const prompt =
    task.tokens_in + task.cache_read_tokens + task.cache_write_tokens
  const total = prompt + task.tokens_out
  const cost = Number(task.cost_total)
  const budget = task.budget == null ? null : Number(task.budget)
  const share = budget ? cost / budget : null
  const rows: Row[] = [
    ['Uncached input', formatTokens(task.tokens_in)],
    ['Cache read', formatTokens(task.cache_read_tokens)],
    ['Cache write', formatTokens(task.cache_write_tokens)],
    ['Output', formatTokens(task.tokens_out)],
  ]
  if (prompt > 0)
    rows.push(['Cache hit', percent(task.cache_read_tokens / prompt)])
  return (
    <StatCard
      icon={<Coins className="text-secondary size-3.5" />}
      label={`${formatTokens(total)} tokens, ${formatMoney(task.cost_total)}`}
      trigger={
        <span className="text-primary text-sm">
          {formatTokens(total)} tok · {formatMoney(task.cost_total)}
          {budget !== null && (
            <span className="text-tertiary"> of {formatMoney(budget)}</span>
          )}
        </span>
      }
    >
      <Section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <span className={cn(share !== null && share > 1 && 'text-danger')}>
            {share === null ? 'No budget' : `${percent(share)} of budget`}
          </span>
          <span className="text-muted-foreground font-mono">
            {formatMoney(cost)}
            {budget !== null && ` / ${formatMoney(budget)}`}
          </span>
        </div>
        {share !== null && (
          <Progress aria-label="Budget used" value={Math.min(share, 1) * 100} />
        )}
      </Section>
      <Section>
        <Rows rows={rows} />
      </Section>
      {models.length > 1 && (
        <Section>
          <p className="text-foreground mb-1.5 font-medium">By model</p>
          <Rows
            rows={models.map((m) => [
              m.model,
              [
                formatTokens(m.input + m.output + m.cacheRead + m.cacheWrite),
                m.cost !== null ? formatMoney(m.cost) : null,
              ]
                .filter(Boolean)
                .join(' · '),
            ])}
          />
        </Section>
      )}
      <Section className="bg-muted/50 flex items-center justify-between">
        <span className="text-muted-foreground">Total</span>
        <span className="font-mono">
          {formatTokens(total)} tokens · {formatMoney(cost)}
        </span>
      </Section>
    </StatCard>
  )
}

function percent(share: number): string {
  return `${Math.round(share * 100)}%`
}

function Rows({ rows }: { rows: Row[] }) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="text-muted-foreground truncate">{label}</dt>
          <dd className="text-foreground text-right font-mono tabular-nums">
            {value}
          </dd>
        </Fragment>
      ))}
    </dl>
  )
}

function Section({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={cn('p-3', className)}>{children}</div>
}

function speed(perSecond: number): string {
  return `${perSecond < 10 ? perSecond.toFixed(1) : Math.round(perSecond)} tok/s`
}

function StatCard({
  children,
  icon,
  label,
  trigger,
}: {
  children: ReactNode
  icon: ReactNode
  label: string
  trigger: ReactNode
}) {
  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
        <Button
          aria-label={label}
          className="text-secondary -mx-1 h-auto gap-1.5 px-1 py-0.5 font-mono font-normal tabular-nums"
          size="sm"
          type="button"
          variant="ghost"
        >
          {icon}
          {trigger}
        </Button>
      </HoverCardTrigger>
      <HoverCardContent
        align="start"
        className="w-64 divide-y overflow-hidden p-0 text-xs"
      >
        {children}
      </HoverCardContent>
    </HoverCard>
  )
}

function time(ms: number): string {
  return ms < 60_000 ? formatDuration(ms) : formatElapsed(ms)
}
