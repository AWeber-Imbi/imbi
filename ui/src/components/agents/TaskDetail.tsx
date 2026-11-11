import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Ban,
  Box,
  Check,
  Circle,
  Clock,
  Coins,
  Pause,
  Play,
  RotateCcw,
  Trash2,
  UserRoundPen,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import {
  controlAgentTask,
  deleteAgentTask,
  reassignAgentTask,
  retryAgentTask,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { RichMarkdown } from '@/components/ui/rich-markdown'
import { Textarea } from '@/components/ui/textarea'
import { UserIdentity } from '@/components/ui/user-identity'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

import { formatMoney } from './agentDraft'
import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'
import { ConversationTab } from './ConversationTab'
import {
  checksFrom,
  formatElapsed,
  formatTokens,
  isFailed,
  phaseTimeline,
  requestsFrom,
  statusLabel,
  statusVariant,
  TRIGGERS,
} from './taskEvents'
import {
  errorMessage,
  useAgentTask,
  useAgentTaskEvents,
  useAgentTaskMutation,
} from './taskQueries'
import { AssociatedProjectsTab, RelatedTasksTab } from './TaskRelations'
import { ChecksTab, Composer, InputRequiredTab } from './TaskTabs'
import { timeline } from './taskTimeline'

type TabKey =
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
  const conversationCount = useMemo(
    () => timeline(events.data ?? []).length,
    [events.data],
  )

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
      count: conversationCount,
      key: 'conversation',
      label: 'Conversation',
    },
    {
      count: failing ? `${failing} failing` : undefined,
      key: 'checks',
      label: 'Signals and checks',
    },
    { key: 'related', label: 'Related tasks' },
    { key: 'projects', label: 'Associated projects' },
  ]
  // Actions taken is part of the Conversation now; keep its old links.
  const wanted = tab === 'actions' ? 'conversation' : tab
  const current: TabKey = tabs.some((x) => x.key === wanted)
    ? (wanted as TabKey)
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
        {current === 'overview' && (
          <OverviewTab end={end} events={log} task={t} />
        )}
        {current === 'input' && (
          <InputRequiredTab orgSlug={orgSlug} requests={requests} task={t} />
        )}
        {current === 'conversation' && (
          <ConversationTab
            events={log}
            orgSlug={orgSlug}
            requests={requests}
            task={t}
          />
        )}
        {current === 'checks' && <ChecksTab events={log} />}
        {current === 'related' && (
          <RelatedTasksTab orgSlug={orgSlug} task={t} />
        )}
        {current === 'projects' && (
          <AssociatedProjectsTab orgSlug={orgSlug} task={t} />
        )}
      </div>
      {t.status !== 'closed' && <Composer orgSlug={orgSlug} task={t} />}
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
  end,
  events,
  task,
}: {
  end: number
  events: AgentTaskEvent[]
  task: AgentTask
}) {
  const [raw, setRaw] = useState(false)
  const todos = [...events].reverse().find((e) => e.type === 'todos.updated')
    ?.payload.todos as undefined | { done?: boolean; title?: string }[]
  const rows: { name: string; value: ReactNode }[] = [
    {
      name: 'Owner',
      value: <UserIdentity email={task.owner} size="small" />,
    },
    { name: 'Started', value: new Date(task.created_at).toLocaleString() },
  ]
  if (task.status === 'closed') {
    rows.push({
      name: 'Outcome',
      value: `${statusLabel(task)}${task.outcome_reason ? ` · ${task.outcome_reason}` : ''}`,
    })
  }
  rows.push(
    {
      name: 'Prompt version',
      value: task.prompt_version == null ? '—' : `v${task.prompt_version}`,
    },
    {
      name: 'Cost / budget',
      value: (
        <>
          {formatMoney(task.cost_total, 6)}
          <span className="text-tertiary">
            {task.budget == null
              ? ' · no budget'
              : ` of ${formatMoney(task.budget, 6)}`}
          </span>
        </>
      ),
    },
    {
      name: 'Tokens in / out',
      value: `${task.tokens_in.toLocaleString()} / ${task.tokens_out.toLocaleString()}`,
    },
    {
      name: 'Cache read / write',
      value: `${task.cache_read_tokens.toLocaleString()} / ${task.cache_write_tokens.toLocaleString()}`,
    },
    {
      name: 'Duration',
      value: formatElapsed(end - Date.parse(task.created_at)),
    },
  )
  return (
    <div className="flex flex-col gap-4 px-6 py-5">
      <Card className="p-5">
        <h3 className="text-overline text-tertiary mb-4 uppercase">Details</h3>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-5 md:grid-cols-3 xl:grid-cols-5">
          {rows.map((row) => (
            <div className="flex min-w-0 flex-col gap-1" key={row.name}>
              <dt className="text-overline text-tertiary uppercase">
                {row.name}
              </dt>
              <dd className="font-mono text-sm wrap-break-word tabular-nums">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="border-tertiary flex items-center justify-between border-b px-5 py-3">
          <h3 className="text-overline text-tertiary uppercase">Description</h3>
          <Button
            onClick={() => setRaw((r) => !r)}
            size="sm"
            type="button"
            variant="outline"
          >
            {raw ? 'View rendered' : 'View raw'}
          </Button>
        </div>
        <div className="p-5">
          {raw ? (
            <pre className="text-primary font-mono text-sm wrap-break-word whitespace-pre-wrap">
              {task.description}
            </pre>
          ) : (
            <div className="document-markdown max-w-3xl text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <RichMarkdown>{task.description}</RichMarkdown>
            </div>
          )}
        </div>
      </Card>
      {todos && todos.length > 0 && (
        <Card className="p-5">
          <h3 className="text-overline text-tertiary mb-3 uppercase">Todos</h3>
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
        </Card>
      )}
    </div>
  )
}

/**
 * Pause or resume, cancel, and reassign. Hidden without
 * `agent_task:manage`.
 */
function TaskControls({ orgSlug, task }: { orgSlug: string; task: AgentTask }) {
  const canManage = useHasPermission('agent_task:manage', orgSlug)
  const [owner, setOwner] = useState('')
  const [open, setOpen] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const { users } = useUserDisplayNames()
  const paused = task.control === 'pause'
  const control = useAgentTaskMutation(orgSlug, task.short_id, () =>
    controlAgentTask(orgSlug, task.short_id, paused ? 'resume' : 'pause'),
  )
  const cancel = useAgentTaskMutation(orgSlug, task.short_id, () =>
    controlAgentTask(orgSlug, task.short_id, 'cancel'),
  )
  const reassign = useAgentTaskMutation(orgSlug, task.short_id, (to: string) =>
    reassignAgentTask(orgSlug, task.short_id, to),
  )
  if (!canManage || task.status === 'closed') return null
  const cancelling = task.control === 'cancel'
  const pending = control.isPending || cancel.isPending
  // Show the error of the most recent failed action.
  const error = [control, cancel, reassign]
    .filter((m) => m.error)
    .sort((a, b) => b.submittedAt - a.submittedAt)[0]?.error
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        aria-label={paused ? 'Resume task' : 'Pause task'}
        disabled={pending || cancelling}
        onClick={() => control.mutate(undefined)}
        size="sm"
        title={paused ? 'Resume' : 'Pause'}
        variant="outline"
      >
        {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
      </Button>
      <Button
        aria-label="Cancel task"
        disabled={pending || cancelling}
        onClick={() => setConfirmCancel(true)}
        size="sm"
        title={cancelling ? 'Cancelling' : 'Cancel'}
        variant="outline"
      >
        <Ban className="size-4" />
      </Button>
      <ConfirmDialog
        confirmLabel="Cancel task"
        description="Imbi closes the task as cancelled_by_human. A runner that holds it stops first. You cannot resume a cancelled task."
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => {
          setConfirmCancel(false)
          cancel.mutate(undefined)
        }}
        open={confirmCancel}
        title={`Cancel ${task.short_id}?`}
      />
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

/** Delete a closed task. Hidden without `agent_task:delete`. */
function TaskDelete({ orgSlug, task }: { orgSlug: string; task: AgentTask }) {
  const canDelete = useHasPermission('agent_task:delete', orgSlug)
  const navigate = useNavigate()
  const [confirm, setConfirm] = useState(false)
  const queryClient = useQueryClient()
  // Navigate before the refresh, so the deleted task is not read again.
  const remove = useMutation({
    mutationFn: () => deleteAgentTask(orgSlug, task.short_id),
    onSuccess: () => {
      navigate(agentsPath('tasks'))
      queryClient.removeQueries({
        queryKey: queryKeys.agentTask(orgSlug, task.short_id),
      })
      for (const queryKey of [
        queryKeys.agentTasks(orgSlug),
        queryKeys.agentTasksWaiting(orgSlug),
      ])
        void queryClient.invalidateQueries({ queryKey })
    },
  })
  if (!canDelete || task.status !== 'closed') return null
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        aria-label="Delete task"
        disabled={remove.isPending}
        onClick={() => setConfirm(true)}
        size="sm"
        title="Delete"
        variant="outline"
      >
        <Trash2 className="size-4" />
      </Button>
      <ConfirmDialog
        confirmLabel="Delete task"
        description="Imbi removes the task, its events, and its relations. The secret audit and the usage records stay. You cannot undo this."
        onCancel={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false)
          remove.mutate()
        }}
        open={confirm}
        title={`Delete ${task.short_id}?`}
      />
      {remove.error && (
        <span className="text-danger text-xs" role="alert">
          {errorMessage(remove.error)}
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
        <TaskRetry orgSlug={orgSlug} task={task} />
        <TaskDelete orgSlug={orgSlug} task={task} />
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
        {task.projects.length > 0 && (
          <Fact icon={<Box className="size-3.5" />}>
            {task.projects.map((p, i) => (
              <span key={p.project_id}>
                {i > 0 && ', '}
                <Link
                  className="font-mono text-xs hover:underline"
                  to={`/projects/${encodeURIComponent(p.project_id)}`}
                >
                  {p.project_slug}
                </Link>
              </span>
            ))}
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

/**
 * Retry a failed task as a new task, with what happened to it and an
 * optional note, then open the new task. Hidden without
 * `agent_task:create`.
 */
function TaskRetry({ orgSlug, task }: { orgSlug: string; task: AgentTask }) {
  const canCreate = useHasPermission('agent_task:create', orgSlug)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  // Keep one key until a retry succeeds, so a repeat after a lost
  // response returns the first copy and does not make a second one.
  const [retryKey, setRetryKey] = useState(() => crypto.randomUUID())
  const retry = useMutation({
    mutationFn: () =>
      retryAgentTask(orgSlug, task.short_id, {
        idempotency_key: retryKey,
        note: note.trim() || null,
      }),
    onSuccess: (copy) => {
      setRetryKey(crypto.randomUUID())
      setOpen(false)
      setNote('')
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentTasks(orgSlug),
      })
      navigate(agentsPath('tasks', orgSlug, copy.short_id))
    },
  })
  // A 400 or 422 means the API did not make the task, so the note
  // can change. Any other error can come after the task was made.
  const rejected =
    retry.error instanceof ApiError &&
    (retry.error.status === 400 || retry.error.status === 422)
  if (!canCreate || !isFailed(task)) return null
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <Button
          aria-label="Retry task"
          size="sm"
          title="Retry as a new task"
          variant="outline"
        >
          <RotateCcw className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-96 flex-col gap-3">
        <p className="text-secondary text-sm">
          Imbi makes a new task with the same agent and description, and adds
          the outcome and the last agent message of {task.short_id}.
        </p>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            retry.mutate()
          }}
        >
          <Textarea
            aria-label="Note for the retry"
            maxLength={64 * 1024}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What should the agent do differently? (optional)"
            // A failed retry can still have made the task, and a repeat
            // with the same key returns it unchanged, so lock the note.
            // Also lock it while the request runs.
            readOnly={retry.isPending || (retry.isError && !rejected)}
            rows={4}
            value={note}
          />
          <Button
            className="self-end"
            disabled={retry.isPending}
            size="sm"
            type="submit"
          >
            Retry
          </Button>
        </form>
        {retry.error && (
          <p className="text-danger text-xs" role="alert">
            {errorMessage(retry.error)}
            {rejected ? '' : ' Retry again to send the same note.'}
          </p>
        )}
      </PopoverContent>
    </Popover>
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
