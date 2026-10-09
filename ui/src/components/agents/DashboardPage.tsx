import type { ReactNode } from 'react'

import { Link } from 'react-router-dom'

import {
  Activity,
  Banknote,
  ChartColumn,
  Clock,
  Hourglass,
  type LucideIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { ErrorBanner } from '@/components/ui/error-banner'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'
import type { AgentTaskListItem, AgentTaskStatus, AgentUsage } from '@/types'

import { formatMoney } from './agentDraft'
import { useAgentList, useAgentUsage } from './agentQueries'
import { agentsPath } from './agentsNav'
import {
  capStatus,
  dailyValues,
  daysBetween,
  formatCount,
  formatDay,
  formatShare,
  sumTotals,
} from './agentUsage'
import {
  formatElapsed,
  groupTasks,
  statusLabel,
  statusVariant,
} from './taskEvents'
import { useAgentTasks, useWaitingTaskCount } from './taskQueries'

const OPEN: AgentTaskStatus[] = ['blocked', 'running', 'paused', 'queued']

// ponytail: like the inbox, the dashboard reads the newest 100 open and
// 50 recent tasks; an org with more needs a summary endpoint.
const OPEN_LIMIT = 100
const RECENT_LIMIT = 50
const RECENT_RUNS = 8
const BUSIEST = 5
const WEEK_MS = 7 * 86_400_000
const HOUR_MS = 3_600_000

/** Closed outcomes that a person should look at. */
const ATTENTION_OUTCOMES = new Set([
  'exceeded_ceiling',
  'failed_at_gate',
  'failed_external',
  'partial_capped',
  'request_expired',
])

interface AttentionItem {
  age: string
  key: string
  kind: string
  meta: string
  title: string
  to: string
  tone: 'danger' | 'warning'
}

interface SparkBar {
  title: string
  value: number
}

/**
 * Agents > Dashboard: agent work at a glance, from the task list, the
 * waiting count, and the usage API.
 */
export function DashboardPage() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('agent_task:read')
  if (!orgSlug || !canRead) {
    return (
      <div className="text-tertiary p-8 text-center">
        {orgSlug
          ? 'You do not have permission to read agent tasks.'
          : 'Select an organization to see agent tasks.'}
      </div>
    )
  }
  return <Dashboard orgSlug={orgSlug} />
}

function BusiestAgents({
  nameOf,
  usage,
}: {
  nameOf: (id: string) => string
  usage: AgentUsage
}) {
  const rows = usage.agents
    .filter((a) => a.tasks > 0)
    .sort((a, b) => b.tasks - a.tasks)
    .slice(0, BUSIEST)
  const max = rows[0]?.tasks ?? 0
  return (
    <Card
      action={<span className="text-tertiary text-xs">30 days</span>}
      title="Busiest agents"
    >
      {rows.length === 0 ? (
        <Empty>No runs in the last 30 days.</Empty>
      ) : (
        <ol className="flex flex-col gap-3 p-5">
          {rows.map((row) => (
            <li className="flex flex-col gap-1" key={row.agent_id}>
              <span className="flex items-baseline justify-between">
                <span className="text-sm">{nameOf(row.agent_id)}</span>
                <span className="text-tertiary font-mono text-xs tabular-nums">
                  {formatCount(row.tasks)}
                </span>
              </span>
              <span className="bg-tertiary h-1.5 w-full overflow-hidden rounded-full">
                <span
                  className="bg-action block h-full"
                  style={{ width: `${(row.tasks / max) * 100}%` }}
                />
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

function Card({
  action,
  children,
  className,
  subtitle,
  title,
}: {
  action?: ReactNode
  children: ReactNode
  className?: string
  subtitle?: string
  title: string
}) {
  return (
    <section
      aria-label={title}
      className={cn('border-border bg-card rounded-lg border', className)}
    >
      <div className="border-border flex items-center justify-between gap-4 border-b px-5 py-4">
        <div>
          <h2 className="text-card-title">{title}</h2>
          {subtitle && <p className="text-tertiary text-xs">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function Dashboard({ orgSlug }: { orgSlug: string }) {
  const open = useAgentTasks(orgSlug, { limit: OPEN_LIMIT, status: OPEN })
  const recent = useAgentTasks(orgSlug, { limit: RECENT_LIMIT })
  const { data: waitingCount } = useWaitingTaskCount(orgSlug)
  const usage = useAgentUsage(orgSlug)
  const { data: agents = [] } = useAgentList(orgSlug)

  const error = open.error ?? recent.error ?? usage.error
  if (error) {
    return (
      <div className="p-8">
        <ErrorBanner error={error} title="Failed to load the dashboard" />
      </div>
    )
  }
  if (!open.data || !recent.data || !usage.data) {
    return <p className="text-tertiary p-8 text-sm">Loading…</p>
  }

  // The time of the last list read: ages change when the lists refresh.
  const now = open.dataUpdatedAt
  const since = (at: null | string | undefined) => now - Date.parse(at ?? '')
  const groups = groupTasks(open.data)
  const group = (id: string) => groups.find((g) => g.id === id)?.tasks ?? []
  // Oldest block first (O2).
  const waiting = group('input')
  const names = new Map(agents.map((a) => [a.id, a.name]))
  const nameOf = (id: string) => names.get(id) ?? id
  const runs = sumTotals(usage.data.agents).tasks
  const mtd = usage.data.month_to_date
  const monthToDate = Object.values(mtd).reduce((n, v) => n + Number(v), 0)
  const days = daysBetween(usage.data.start, usage.data.end)
  const spark = (values: number[], format: (n: number) => string) =>
    values.map((value, i) => ({
      title: `${formatDay(days[i])} · ${format(value)}`,
      value,
    }))

  const attention: AttentionItem[] = [
    ...waiting.map(
      (t): AttentionItem => ({
        age: formatElapsed(since(t.blocked_since)),
        key: t.id,
        kind: 'Waiting',
        meta: `${t.short_id} · ${nameOf(t.agent_id)} · ${t.owner}`,
        title: t.title,
        to: agentsPath('tasks', orgSlug, t.short_id, 'input'),
        tone: 'warning',
      }),
    ),
    ...recent.data
      .filter(
        (t) =>
          !!t.outcome &&
          ATTENTION_OUTCOMES.has(t.outcome) &&
          since(t.closed_at) < WEEK_MS,
      )
      .sort((a, b) => since(a.closed_at) - since(b.closed_at))
      .map(
        (t): AttentionItem => ({
          age: formatElapsed(since(t.closed_at)),
          key: t.id,
          kind: statusLabel(t),
          meta: [t.short_id, nameOf(t.agent_id), t.outcome_reason]
            .filter(Boolean)
            .join(' · '),
          title: t.title,
          to: agentsPath('tasks', orgSlug, t.short_id),
          tone: statusVariant(t) === 'danger' ? 'danger' : 'warning',
        }),
      ),
    // The advisory monthly cost cap (ADR 0020): 80% and 100%.
    ...agents.flatMap((a): AttentionItem[] => {
      const cap = capStatus(a, Number(mtd[a.id] ?? 0))
      return cap
        ? [
            {
              age: '',
              key: `cap-${a.id}`,
              kind: 'Budget',
              meta: `${formatMoney(cap.spent)} of ${formatMoney(cap.cap)} this month · advisory, the agent still runs`,
              title: `${a.name} is at ${formatShare(cap.share)} of its monthly cost cap`,
              to: agentsPath('manage', a.slug),
              tone: cap.level === 'over' ? 'danger' : 'warning',
            },
          ]
        : []
    }),
  ]

  return (
    <div className="flex flex-col gap-6 p-8">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Tile
          icon={Activity}
          label="Running"
          note="now"
          to={agentsPath('tasks')}
          value={formatCount(group('running').length)}
        />
        <Tile
          icon={Hourglass}
          label="Waiting on people"
          note={
            waiting.length
              ? `oldest ${formatElapsed(since(waiting[0].blocked_since))}`
              : 'nobody waiting'
          }
          to={agentsPath('tasks')}
          value={formatCount(waitingCount ?? waiting.length)}
          warn={waiting.length > 0}
        />
        <Tile
          icon={Clock}
          label="Queued"
          note="now"
          to={agentsPath('tasks')}
          value={formatCount(group('queued').length)}
        />
        <Tile
          icon={ChartColumn}
          label="Runs"
          note="30 days"
          spark={spark(
            dailyValues(usage.data, (r) => r.tasks),
            (n) => `${formatCount(n)} runs`,
          )}
          to={agentsPath('usage')}
          value={formatCount(runs)}
        />
        <Tile
          icon={Banknote}
          label="Spend this month"
          note="month to date"
          spark={spark(
            dailyValues(usage.data, (r) => Number(r.cost)),
            (n) => formatMoney(n),
          )}
          to={agentsPath('usage')}
          value={formatMoney(monthToDate)}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <NeedsAttention
          className="xl:col-span-2"
          items={attention}
          runs={runs}
        />
        <BusiestAgents nameOf={nameOf} usage={usage.data} />
      </div>

      <WaitingOnPeople since={since} tasks={waiting} />

      <RecentRuns
        nameOf={nameOf}
        orgSlug={orgSlug}
        tasks={recent.data.slice(0, RECENT_RUNS)}
      />
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="text-tertiary px-5 py-10 text-center text-sm">{children}</p>
  )
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * Tasks that wait on a person (oldest block first, O2), closed tasks
 * that failed or hit a cap in the last 7 days, and monthly cost caps.
 */
function NeedsAttention({
  className,
  items,
  runs,
}: {
  className?: string
  items: AttentionItem[]
  runs: number
}) {
  return (
    <Card
      action={
        <span className="text-tertiary font-mono text-xs tabular-nums">
          {items.length} open
        </span>
      }
      className={className}
      title="Needs attention"
    >
      {items.length === 0 ? (
        // The trailing volume shows that an empty queue is healthy (O2).
        <Empty>
          Nothing needs attention. {formatCount(runs)} run
          {runs === 1 ? '' : 's'} in the last 30 days.
        </Empty>
      ) : (
        <ul>
          {items.map((item) => (
            <li
              className="border-border border-b last:border-b-0"
              key={item.key}
            >
              <Link
                className="hover:bg-secondary flex items-center gap-4 px-5 py-3 transition-colors"
                to={item.to}
              >
                <Badge variant={item.tone}>{item.kind}</Badge>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{item.title}</span>
                  <span className="text-tertiary block truncate text-xs">
                    {item.meta}
                  </span>
                </span>
                <span className="text-tertiary font-mono text-xs tabular-nums">
                  {item.age}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function RecentRuns({
  nameOf,
  orgSlug,
  tasks,
}: {
  nameOf: (id: string) => string
  orgSlug: string
  tasks: AgentTaskListItem[]
}) {
  return (
    <Card
      action={
        <Link
          className="text-action text-sm hover:underline"
          to={agentsPath('tasks')}
        >
          All tasks
        </Link>
      }
      title="Recent runs"
    >
      {tasks.length === 0 ? (
        <Empty>No tasks yet. Start one with Run on an agent.</Empty>
      ) : (
        <ul>
          {tasks.map((t) => (
            <li className="border-border border-b last:border-b-0" key={t.id}>
              <Link
                className="hover:bg-secondary flex items-center gap-4 px-5 py-3 transition-colors"
                to={agentsPath('tasks', orgSlug, t.short_id)}
              >
                <span className="text-tertiary w-16 shrink-0 font-mono text-xs tabular-nums">
                  {t.short_id}
                </span>
                <span className="w-32 shrink-0 truncate text-sm">
                  {nameOf(t.agent_id)}
                </span>
                <span className="text-secondary min-w-0 flex-1 truncate text-sm">
                  {t.title}
                </span>
                <Badge variant={statusVariant(t)}>{statusLabel(t)}</Badge>
                <span className="text-tertiary w-20 text-right font-mono text-xs tabular-nums">
                  {formatMoney(t.cost_total)}
                </span>
                <RelativeTime
                  className="text-tertiary w-12 text-right text-xs"
                  tooltip={false}
                  value={t.created_at}
                  variant="narrow"
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Tile({
  icon: Icon,
  label,
  note,
  spark,
  to,
  value,
  warn,
}: {
  icon: LucideIcon
  label: string
  note: string
  spark?: SparkBar[]
  to: string
  value: string
  warn?: boolean
}) {
  const max = Math.max(0, ...(spark ?? []).map((s) => s.value))
  return (
    <Link
      className="border-tertiary bg-primary hover:bg-secondary flex flex-col rounded-lg border p-5 transition-colors"
      to={to}
    >
      <span className="flex items-start justify-between">
        <span className="text-overline text-tertiary uppercase">{label}</span>
        <Icon className="text-tertiary size-4" />
      </span>
      <span className="mt-2 flex items-end justify-between gap-3">
        <span className="flex flex-col">
          <span
            className={cn(
              'font-mono text-2xl tracking-tight tabular-nums',
              warn && 'text-warning',
            )}
          >
            {value}
          </span>
          <span className="text-tertiary mt-1 text-xs">{note}</span>
        </span>
        {spark && (
          <span
            aria-label={`${label} per day`}
            className="flex h-8.5 w-24 items-end gap-px"
            role="img"
          >
            {spark.map((s, i) => (
              <span
                className={cn(
                  'bg-action flex-1 rounded-[1px]',
                  i < spark.length - 1 && 'opacity-30',
                )}
                key={i}
                style={{
                  height: `${max > 0 ? Math.max(8, (s.value / max) * 100) : 8}%`,
                }}
                title={s.title}
              />
            ))}
          </span>
        )}
      </span>
    </Link>
  )
}

/** The tasks that wait on a request, by owner, longest wait first. */
function WaitingOnPeople({
  since,
  tasks,
}: {
  since: (at: null | string | undefined) => number
  tasks: AgentTaskListItem[]
}) {
  // `tasks` is oldest block first, so the owners come longest wait
  // first and each owner's waits come longest first.
  const owners = new Map<string, number[]>()
  for (const t of tasks)
    owners.set(t.owner, [
      ...(owners.get(t.owner) ?? []),
      since(t.blocked_since),
    ])
  const rows = [...owners]
  const waits = tasks.map((t) => since(t.blocked_since))
  const longest = waits[0] ?? 0
  const head = 'text-overline text-tertiary px-5 py-2.5 uppercase'
  const stat = (name: string, value: string, className?: string) => (
    <span className="flex flex-col text-right">
      <span className="text-overline text-tertiary uppercase">{name}</span>
      <span className={cn('font-mono text-sm tabular-nums', className)}>
        {value}
      </span>
    </span>
  )
  return (
    <Card
      action={
        <span className="flex items-center gap-6">
          {stat('Tasks', formatCount(tasks.length))}
          {stat(
            'Median wait',
            waits.length ? formatElapsed(median(waits)) : '—',
          )}
          {stat(
            'Oldest',
            waits.length ? formatElapsed(longest) : '—',
            waits.length ? 'text-danger' : undefined,
          )}
          <Link
            className="text-action text-sm hover:underline"
            to={agentsPath('tasks')}
          >
            View all
          </Link>
        </span>
      }
      subtitle="Tasks with an open feedback or approval request, by owner"
      title="Waiting on people"
    >
      {rows.length === 0 ? (
        <Empty>Nobody is waiting on a request.</Empty>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-border bg-secondary border-b">
              <th className={`${head} text-left`}>Person</th>
              <th className={`${head} text-right`}>Waiting</th>
              <th className={`${head} text-left`}>Oldest wait</th>
              <th className={`${head} text-right`}>Median</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([owner, ms]) => (
              <tr
                className="border-border border-b last:border-b-0"
                key={owner}
              >
                <td className="px-5 py-3">
                  <UserIdentity email={owner} size="small" />
                </td>
                <td className="px-5 py-3 text-right font-mono text-sm tabular-nums">
                  {ms.length}
                </td>
                <td className="px-5 py-3">
                  <span className="flex items-center gap-3">
                    <span className="bg-tertiary h-1.5 w-24 overflow-hidden rounded-full">
                      <span
                        className={cn(
                          'block h-full',
                          ms[0] > 24 * HOUR_MS
                            ? 'bg-danger'
                            : ms[0] > 4 * HOUR_MS
                              ? 'bg-warning'
                              : 'bg-action',
                        )}
                        style={{ width: `${(ms[0] / (longest || 1)) * 100}%` }}
                      />
                    </span>
                    <span className="text-secondary font-mono text-xs tabular-nums">
                      {formatElapsed(ms[0])}
                    </span>
                  </span>
                </td>
                <td className="text-secondary px-5 py-3 text-right font-mono text-sm tabular-nums">
                  {formatElapsed(median(ms))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
