import { type ReactNode, useEffect, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import {
  Box,
  Check,
  Circle,
  Clock,
  Coins,
  Pause,
  Play,
  UserRoundPen,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import { controlAgentTask, reassignAgentTask } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { UserIdentity } from '@/components/ui/user-identity'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

import { formatMoney } from './agentDraft'
import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'
import {
  checksFrom,
  conversation,
  formatElapsed,
  formatTokens,
  phaseTimeline,
  requestsFrom,
  statusLabel,
  statusVariant,
  toolCalls,
  TRIGGERS,
} from './taskEvents'
import {
  errorMessage,
  useAgentTask,
  useAgentTaskEvents,
  useAgentTaskMutation,
} from './taskQueries'
import { AssociatedProjectsTab, RelatedTasksTab } from './TaskRelations'
import {
  ActionsTab,
  ChecksTab,
  ConversationTab,
  InputRequiredTab,
} from './TaskTabs'

type TabKey =
  | 'actions'
  | 'checks'
  | 'conversation'
  | 'input'
  | 'overview'
  | 'projects'
  | 'related'

/** The task in the inbox: its header, phase timeline, and tabs. */
export function TaskDetail({
  orgSlug,
  shortId,
  tab,
}: {
  orgSlug: string
  shortId: string
  tab?: string
}) {
  const navigate = useNavigate()
  const task = useAgentTask(orgSlug, shortId)
  const live = !!task.data && task.data.status !== 'closed'
  const events = useAgentTaskEvents(orgSlug, shortId, live)
  const now = useNow(live)

  if (task.isLoading) {
    return <p className="text-tertiary p-6 text-sm">Loading…</p>
  }
  if (!task.data) {
    return (
      <p className="text-secondary p-6 text-sm" role="alert">
        {task.error instanceof ApiError && task.error.status === 404
          ? `No task ${shortId} in this organization.`
          : `Could not load ${shortId}: ${task.error?.message ?? ''}`}
      </p>
    )
  }

  const t = task.data
  const log = events.data ?? []
  const end = t.closed_at ? Date.parse(t.closed_at) : now
  const requests = requestsFrom(log, now)
  const open = requests.filter((r) => r.status === 'open').length
  const failing = checksFrom(log).filter(
    (e) => e.payload.verdict === 'fail',
  ).length
  const tabs: { count?: number | string; key: TabKey; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { count: open, key: 'input', label: 'Input required' },
    {
      count: conversation(log).length,
      key: 'conversation',
      label: 'Conversation',
    },
    { count: toolCalls(log).length, key: 'actions', label: 'Actions taken' },
    {
      count: failing ? `${failing} failing` : undefined,
      key: 'checks',
      label: 'Signals and checks',
    },
    { key: 'related', label: 'Related tasks' },
    { key: 'projects', label: 'Associated projects' },
  ]
  const current: TabKey = tabs.some((x) => x.key === tab)
    ? (tab as TabKey)
    : 'overview'

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TaskHeader end={end} events={log} orgSlug={orgSlug} task={t} />
      <div
        className="border-tertiary flex shrink-0 gap-1 border-b px-4"
        role="tablist"
      >
        {tabs.map((x) => (
          <button
            aria-selected={current === x.key}
            className={cn(
              '-mb-px border-b-2 px-3 py-2.5 text-sm whitespace-nowrap',
              current === x.key
                ? 'border-action font-medium text-primary'
                : 'border-transparent text-secondary hover:text-primary',
              x.key === 'input' && open > 0 && 'text-amber-text',
            )}
            key={x.key}
            onClick={() =>
              navigate(agentsPath('tasks', orgSlug, shortId, x.key))
            }
            role="tab"
            type="button"
          >
            {x.label}
            {x.count !== undefined && (
              <span className="text-tertiary ml-2 font-mono text-xs tabular-nums">
                {x.count}
              </span>
            )}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {events.error && (
          <p className="text-danger px-6 pt-4 text-sm" role="alert">
            Could not load the task log: {events.error.message}
          </p>
        )}
        {current === 'overview' && <OverviewTab events={log} task={t} />}
        {current === 'input' && (
          <InputRequiredTab orgSlug={orgSlug} requests={requests} task={t} />
        )}
        {current === 'conversation' && (
          <ConversationTab events={log} orgSlug={orgSlug} task={t} />
        )}
        {current === 'actions' && <ActionsTab events={log} orgSlug={orgSlug} />}
        {current === 'checks' && <ChecksTab events={log} />}
        {current === 'related' && (
          <RelatedTasksTab orgSlug={orgSlug} task={t} />
        )}
        {current === 'projects' && (
          <AssociatedProjectsTab orgSlug={orgSlug} task={t} />
        )}
      </div>
    </div>
  )
}

function Fact({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <span className="text-secondary flex items-center gap-1.5 text-sm">
      {icon}
      {children}
    </span>
  )
}

function OverviewTab({
  events,
  task,
}: {
  events: AgentTaskEvent[]
  task: AgentTask
}) {
  const todos = [...events].reverse().find((e) => e.type === 'todos.updated')
    ?.payload.todos as undefined | { done?: boolean; title?: string }[]
  const rows: { name: string; value: ReactNode }[] = [
    {
      name: 'Owner',
      value: <UserIdentity email={task.owner} size="small" />,
    },
    { name: 'Started', value: new Date(task.created_at).toLocaleString() },
    {
      name: 'Budget',
      value: task.budget == null ? 'No budget' : formatMoney(task.budget, 6),
    },
    { name: 'Cost', value: formatMoney(task.cost_total, 6) },
    {
      name: 'Tokens in / out',
      value: `${task.tokens_in.toLocaleString()} / ${task.tokens_out.toLocaleString()}`,
    },
    {
      name: 'Cache read / write',
      value: `${task.cache_read_tokens.toLocaleString()} / ${task.cache_write_tokens.toLocaleString()}`,
    },
    {
      name: 'Prompt version',
      value: task.prompt_version == null ? '—' : `v${task.prompt_version}`,
    },
  ]
  if (task.status === 'closed') {
    rows.push({
      name: 'Outcome',
      value: `${statusLabel(task)}${task.outcome_reason ? ` · ${task.outcome_reason}` : ''}`,
    })
  }
  return (
    <div className="flex flex-col gap-6 px-6 py-5">
      <section>
        <h3 className="text-overline text-tertiary mb-2 uppercase">
          Description
        </h3>
        <p className="text-primary text-sm whitespace-pre-wrap">
          {task.description}
        </p>
      </section>
      {todos && todos.length > 0 && (
        <section>
          <h3 className="text-overline text-tertiary mb-2 uppercase">Todos</h3>
          <ul className="flex flex-col gap-1">
            {todos.map((todo, i) => (
              <li className="flex items-center gap-2 text-sm" key={i}>
                {todo.done ? (
                  <Check className="text-success size-3.5" />
                ) : (
                  <Circle className="text-tertiary size-3.5" />
                )}
                <span className={todo.done ? 'text-secondary' : ''}>
                  {todo.title}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <dl className="grid grid-cols-2 gap-x-8 gap-y-4 xl:grid-cols-3">
        {rows.map((row) => (
          <div className="flex flex-col gap-1" key={row.name}>
            <dt className="text-overline text-tertiary uppercase">
              {row.name}
            </dt>
            <dd className="font-mono text-sm">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Pause or resume, and reassign. Hidden without `agent_task:manage`. */
function TaskControls({ orgSlug, task }: { orgSlug: string; task: AgentTask }) {
  const canManage = useHasPermission('agent_task:manage')
  const [owner, setOwner] = useState('')
  const [open, setOpen] = useState(false)
  const { users } = useUserDisplayNames()
  const paused = task.control === 'pause'
  const control = useAgentTaskMutation(orgSlug, task.short_id, () =>
    controlAgentTask(orgSlug, task.short_id, paused ? 'resume' : 'pause'),
  )
  const reassign = useAgentTaskMutation(orgSlug, task.short_id, (to: string) =>
    reassignAgentTask(orgSlug, task.short_id, to),
  )
  if (!canManage || task.status === 'closed') return null
  const error = control.error ?? reassign.error
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        aria-label={paused ? 'Resume task' : 'Pause task'}
        disabled={control.isPending || task.control === 'cancel'}
        onClick={() => control.mutate(undefined)}
        size="sm"
        title={paused ? 'Resume' : 'Pause'}
        variant="outline"
      >
        {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
      </Button>
      <Popover onOpenChange={setOpen} open={open}>
        <PopoverTrigger asChild>
          <Button
            aria-label="Reassign task"
            size="sm"
            title="Reassign"
            variant="outline"
          >
            <UserRoundPen className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="flex flex-col gap-3">
          <div className="text-sm">
            Owner:{' '}
            <UserIdentity
              email={task.owner}
              linkToProfile={false}
              size="small"
            />
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              reassign.mutate(owner.trim(), {
                onSuccess: () => {
                  setOpen(false)
                  setOwner('')
                },
              })
            }}
          >
            <Input
              aria-label="New owner email"
              className="h-9 text-sm"
              list="agent-task-owners"
              onChange={(e) => setOwner(e.target.value)}
              placeholder="person@example.com"
              required
              type="email"
              value={owner}
            />
            <datalist id="agent-task-owners">
              {users.map((u) => (
                <option key={u.email} value={u.email}>
                  {u.display_name}
                </option>
              ))}
            </datalist>
            <Button disabled={reassign.isPending} size="sm" type="submit">
              Reassign
            </Button>
          </form>
          {reassign.error && (
            <p className="text-danger text-xs" role="alert">
              {errorMessage(reassign.error)}
            </p>
          )}
        </PopoverContent>
      </Popover>
      {error && !open && (
        <span className="text-danger text-xs" role="alert">
          {errorMessage(error)}
        </span>
      )}
    </div>
  )
}

/**
 * `cost_total` and the token totals sit at title rank (F7), next to the
 * total age; the timeline gives the time in each phase.
 */
function TaskHeader({
  end,
  events,
  orgSlug,
  task,
}: {
  end: number
  events: AgentTaskEvent[]
  orgSlug: string
  task: AgentTask
}) {
  const { data: agents } = useAgentList(orgSlug)
  const agent = agents?.find((a) => a.id === task.agent_id)
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
  const tokens =
    task.tokens_in +
    task.tokens_out +
    task.cache_read_tokens +
    task.cache_write_tokens
  const phases = phaseTimeline(events, end)
  return (
    <div className="border-tertiary flex shrink-0 flex-col gap-3 border-b px-6 pt-5 pb-4">
      <div className="flex items-start gap-3">
        <span className="text-tertiary pt-0.5 font-mono text-sm">
          {task.short_id}
        </span>
        <h2 className="min-w-0 flex-1 text-lg font-medium text-pretty">
          {task.title}
        </h2>
        <Badge variant={statusVariant(task)}>{statusLabel(task)}</Badge>
        <TaskControls orgSlug={orgSlug} task={task} />
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Fact>
          {agent ? (
            <Link
              className="text-primary font-medium hover:underline"
              to={agentsPath('manage', agent.slug)}
            >
              {agent.name}
            </Link>
          ) : (
            <span className="font-mono text-xs">{task.agent_id}</span>
          )}
          <span className="text-tertiary font-mono text-xs">
            v{task.agent_version}
          </span>
        </Fact>
        {task.project_id && (
          <Fact icon={<Box className="size-3.5" />}>
            <Link
              className="font-mono text-xs hover:underline"
              to={`/projects/${encodeURIComponent(task.project_id)}`}
            >
              {task.project_slug ?? task.project_id}
            </Link>
          </Fact>
        )}
        <Fact icon={<TriggerIcon className="size-3.5" />}>
          {trigger.label}
          {task.origin.user && ` · ${task.origin.user}`}
        </Fact>
        <Fact icon={<Clock className="size-3.5" />}>
          <span className="font-mono text-xs tabular-nums">
            {formatElapsed(end - Date.parse(task.created_at))}
          </span>
        </Fact>
        <span className="text-primary flex items-center gap-1.5 font-mono text-sm tabular-nums">
          <Coins className="text-secondary size-3.5" />
          {formatTokens(tokens)} tok · {formatMoney(task.cost_total)}
          {task.budget != null && (
            <span className="text-tertiary">
              {' '}
              of {formatMoney(task.budget)}
            </span>
          )}
        </span>
      </div>
      {phases.length > 0 && (
        <ol aria-label="Phases" className="flex flex-wrap gap-x-6 gap-y-2">
          {phases.map((p, i) => {
            const current = i === phases.length - 1 && task.status !== 'closed'
            return (
              <li className="flex items-center gap-2" key={`${p.at}-${i}`}>
                {current ? (
                  <Circle className="text-action size-3.5" />
                ) : (
                  <Check className="text-action size-3.5" />
                )}
                <span
                  className={cn(
                    'text-sm',
                    current ? 'text-primary font-medium' : 'text-secondary',
                  )}
                >
                  {p.phase}
                </span>
                <span className="text-tertiary font-mono text-xs tabular-nums">
                  {formatElapsed(p.ms)}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

/** The time now, ticking each second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [active])
  return now
}
