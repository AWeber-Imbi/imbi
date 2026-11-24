import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { Link, useLocation, useNavigate } from 'react-router-dom'

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  Ban,
  Box,
  Check,
  Circle,
  Pause,
  Play,
  RotateCcw,
  Trash2,
  UserRoundPen,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import {
  controlTicket,
  deleteTicket,
  getTicketSchema,
  rankTicket,
  reassignTicket,
  retryTicket,
  setTicketPriority,
  updateTicket,
} from '@/api/endpoints'
import { BlueprintFields } from '@/components/ProjectAttributesSection'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DatePicker } from '@/components/ui/date-picker'
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
import type { Ticket, TicketEvent, TicketUpdate } from '@/types'

import {
  type ActivityView,
  ActivityViewSwitch,
  isActivityView,
} from './activityView'
import { formatMoney } from './agentDraft'
import { useAgentList } from './agentQueries'
import { agentsPath, ticketsPath } from './agentsNav'
import { ConversationTab } from './ConversationTab'
import type { RevealState } from './conversationTurns'
import { HandOffControl } from './HandOffControl'
import { PersonStatusControls } from './PersonStatusControls'
import { PriorityBadge, priorityLabel, PriorityPicker } from './priority'
import { StatisticsTab } from './StatisticsTab'
import {
  checksFrom,
  formatElapsed,
  isFailed,
  phaseTimeline,
  requestsFrom,
  statusLabel,
  statusVariant,
  TRIGGERS,
} from './taskEvents'
import {
  errorMessage,
  useTaskReply,
  useTicket,
  useTicketEvents,
  useTicketMutation,
} from './taskQueries'
import { AssociatedProjectsTab, RelatedTasksTab } from './TaskRelations'
import { TaskSearchProvider } from './taskSearch'
import { ChecksTab, Composer, InputRequiredTab } from './TaskTabs'
import { ToolbarLead } from './TaskToolbar'
import { TaskActivityCard, TaskUsageCard } from './TaskUsageCards'
import {
  DueDate,
  LabelInput,
  LabelLink,
  roleErrors,
  roleRows,
  RolesEditor,
  rolesOf,
  TeamPicker,
  TICKET_TYPES,
  TypePicker,
  usePeople,
} from './ticketAttributes'
import { TicketReopen } from './TicketReopen'
import { buildTrajectory } from './trajectoryModel'
import { TrajectoryTab } from './TrajectoryTab'
import { useStoredState } from './useStoredState'

/** A tab, or one view of the Activity tab: what the URL names. */
type RouteKey = ActivityView | TabKey

type TabKey =
  | 'activity'
  | 'checks'
  | 'input'
  | 'overview'
  | 'projects'
  | 'related'

const TAB_KEYS: readonly TabKey[] = [
  'activity',
  'checks',
  'input',
  'overview',
  'projects',
  'related',
]

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
  const { hash, search } = useLocation()
  const task = useTicket(orgSlug, shortId)
  const live = !!task.data && task.data.status !== 'closed'
  const events = useTicketEvents(orgSlug, shortId, live)
  const now = useNow(live)
  const [lastTab, setLastTab] = useStoredState<RouteKey>(
    'imbi.task.tab',
    'overview',
    (raw) => (isRouteKey(raw) ? raw : undefined),
  )
  const [lastView, setLastView] = useStoredState<ActivityView>(
    'imbi.task.view',
    'conversation',
    (raw) => (isActivityView(raw) ? raw : undefined),
  )
  const [draft, setDraft] = useState('')
  const pointer = useRef<null | string>(null)
  const reply = useTaskReply(orgSlug, shortId)
  useEffect(() => {
    const shown = legacyRoute(tab)
    if (isRouteKey(shown)) setLastTab(shown)
    if (isActivityView(shown)) setLastView(shown)
  }, [setLastTab, setLastView, tab])
  const trajectoryCount = useMemo(
    () => buildTrajectory(events.data ?? [], false).records.length,
    [events.data],
  )
  useEffect(() => {
    const linked = /^#e\d+$/.test(hash)
    // Keep the search, so the inbox filters stay.
    if (tab === undefined) {
      navigate(
        linked
          ? `${ticketsPath(orgSlug, shortId, 'trajectory')}${search}${hash}`
          : `${ticketsPath(orgSlug, shortId, lastTab)}${search}`,
        { replace: true },
      )
      return
    }
    const old =
      tab === 'log' ||
      (linked &&
        (tab === 'activity' || tab === 'conversation' || tab === 'actions'))
    if (!old) return
    navigate(
      `${ticketsPath(orgSlug, shortId, 'trajectory')}${search}${linked ? hash : ''}`,
      { replace: true },
    )
  }, [hash, lastTab, navigate, orgSlug, search, shortId, tab])

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
    { count: trajectoryCount, key: 'activity', label: 'Activity' },
    {
      count: failing ? `${failing} failing` : undefined,
      key: 'checks',
      label: 'Signals and checks',
    },
    { key: 'related', label: 'Related tickets' },
    { key: 'projects', label: 'Associated projects' },
  ]
  const wanted = legacyRoute(tab)
  const route: RouteKey = isRouteKey(wanted)
    ? wanted
    : tab === undefined
      ? lastTab
      : 'overview'
  const view: ActivityView | null = isActivityView(route)
    ? route
    : route === 'activity'
      ? lastView
      : null
  const current: TabKey = view ? 'activity' : (route as TabKey)
  const go = (key: RouteKey) => navigate(ticketsPath(orgSlug, shortId, key))
  const showInConversation = (seq: number) =>
    navigate(ticketsPath(orgSlug, shortId, 'conversation'), {
      state: { revealSeq: seq } satisfies RevealState,
    })
  const inspectInTrajectory = (seq: number) => {
    if (tab !== 'conversation')
      navigate(`${ticketsPath(orgSlug, shortId, 'conversation')}${search}`, {
        replace: true,
      })
    navigate(`${ticketsPath(orgSlug, shortId, 'trajectory')}#e${seq}`)
  }

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
            onClick={() => go(x.key === 'activity' ? lastView : x.key)}
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
      {events.error && (
        <p className="text-danger shrink-0 px-6 pt-4 text-sm" role="alert">
          Could not load the task log: {events.error.message}
        </p>
      )}
      <TaskSearchProvider key={t.id}>
        <ToolbarLead.Provider
          value={view && <ActivityViewSwitch onChange={go} value={view} />}
        >
          {view === 'conversation' ? (
            <ConversationTab
              events={log}
              footer={
                t.status === 'closed' ? undefined : (
                  <Composer
                    body={draft}
                    onBodyChange={setDraft}
                    orgSlug={orgSlug}
                    pointer={pointer}
                    reply={reply}
                  />
                )
              }
              onInspect={inspectInTrajectory}
              orgSlug={orgSlug}
              requests={requests}
              task={t}
            />
          ) : view === 'trajectory' ? (
            <TrajectoryTab
              events={log}
              onShowInConversation={showInConversation}
              task={t}
            />
          ) : view === 'statistics' ? (
            <StatisticsTab
              events={log}
              onShowInConversation={showInConversation}
              task={t}
            />
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              {current === 'overview' && (
                <OverviewTab
                  end={end}
                  events={log}
                  orgSlug={orgSlug}
                  task={t}
                />
              )}
              {current === 'input' && (
                <InputRequiredTab
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
          )}
        </ToolbarLead.Provider>
      </TaskSearchProvider>
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

function isRouteKey(value: unknown): value is RouteKey {
  return TAB_KEYS.includes(value as TabKey) || isActivityView(value)
}

/** The route an old tab name now opens. */
function legacyRoute(tab: string | undefined): string | undefined {
  return tab === 'actions' ? 'conversation' : tab === 'log' ? 'trajectory' : tab
}

function OverviewTab({
  end,
  events,
  orgSlug,
  task,
}: {
  end: number
  events: TicketEvent[]
  orgSlug: string
  task: Ticket
}) {
  const [raw, setRaw] = useState(false)
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const priority = useTicketMutation(
    orgSlug,
    task.short_id,
    (to: Ticket['priority']) => setTicketPriority(orgSlug, task.short_id, to),
  )
  const update = useTicketMutation(
    orgSlug,
    task.short_id,
    (body: TicketUpdate) => updateTicket(orgSlug, task.short_id, body),
  )
  const editable = canManage && task.status !== 'closed'
  const todos = [...events].reverse().find((e) => e.type === 'todos.updated')
    ?.payload.todos as undefined | { done?: boolean; title?: string }[]
  const rows: { name: string; value: ReactNode }[] = [
    {
      name: 'Owner',
      value: <UserIdentity email={task.owner} size="small" />,
    },
    {
      name: 'Priority',
      value:
        canManage && task.status !== 'closed' ? (
          <>
            <PriorityPicker
              className="h-8 *:h-full *:py-0"
              disabled={priority.isPending}
              onChange={(to) => priority.mutate(to)}
              value={task.priority}
            />
            {priority.error && (
              <span className="text-danger block text-xs" role="alert">
                {errorMessage(priority.error)}
              </span>
            )}
          </>
        ) : (
          priorityLabel(task.priority)
        ),
    },
    {
      name: 'Type',
      value: editable ? (
        <TypePicker
          className="h-8 *:h-full *:py-0"
          disabled={update.isPending}
          onChange={(type) => update.mutate({ type })}
          value={task.type}
        />
      ) : (
        TICKET_TYPES.find((t) => t.value === task.type)?.label
      ),
    },
    {
      name: 'Due',
      value: editable ? (
        <DatePicker
          aria-label="Due date"
          className="font-sans"
          disabled={update.isPending}
          disablePast
          onChange={(due) => update.mutate({ due_date: due || null })}
          value={task.due_date ?? ''}
        />
      ) : task.due_date ? (
        <DueDate due={task.due_date} />
      ) : (
        '—'
      ),
    },
    {
      name: 'Team',
      value: editable ? (
        <TeamPicker
          className="h-8 w-full max-w-60 font-sans"
          disabled={update.isPending}
          onChange={(slug) => update.mutate({ team: slug || null })}
          orgSlug={orgSlug}
          value={task.team?.slug ?? ''}
        />
      ) : (
        (task.team?.name ?? '—')
      ),
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
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-x-8 gap-y-5">
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
        {update.error && (
          <p className="text-danger mt-3 text-xs" role="alert">
            {errorMessage(update.error)}
          </p>
        )}
      </Card>
      <TicketCustomFields editable={editable} orgSlug={orgSlug} task={task} />
      <TicketPeopleAndLabels
        editable={editable}
        onUpdate={(body, onSuccess) => update.mutate(body, { onSuccess })}
        orgSlug={orgSlug}
        pending={update.isPending}
        task={task}
      />
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

/** The statuses of a ticket in the backlog (the Queued group). */
const BACKLOG = new Set<Ticket['status']>(['held', 'open', 'queued'])

/**
 * Pause or resume, cancel, and reassign. Hidden without
 * `ticket:manage`.
 */
function TaskControls({ orgSlug, task }: { orgSlug: string; task: Ticket }) {
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const [owner, setOwner] = useState('')
  const [open, setOpen] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const { users } = useUserDisplayNames()
  const paused = task.control === 'pause'
  const control = useTicketMutation(orgSlug, task.short_id, () =>
    controlTicket(orgSlug, task.short_id, paused ? 'resume' : 'pause'),
  )
  const cancel = useTicketMutation(orgSlug, task.short_id, () =>
    controlTicket(orgSlug, task.short_id, 'cancel'),
  )
  const reassign = useTicketMutation(orgSlug, task.short_id, (to: string) =>
    reassignTicket(orgSlug, task.short_id, to),
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
        aria-label={paused ? 'Resume ticket' : 'Pause ticket'}
        disabled={pending || cancelling}
        onClick={() => control.mutate(undefined)}
        size="sm"
        title={paused ? 'Resume' : 'Pause'}
        variant="outline"
      >
        {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
      </Button>
      <Button
        aria-label="Cancel ticket"
        disabled={pending || cancelling}
        onClick={() => setConfirmCancel(true)}
        size="sm"
        title={cancelling ? 'Cancelling' : 'Cancel'}
        variant="outline"
      >
        <Ban className="size-4" />
      </Button>
      <ConfirmDialog
        confirmLabel="Cancel ticket"
        description="Imbi closes the ticket as cancelled_by_human. A runner that holds it stops first. You cannot resume a cancelled ticket."
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
            aria-label="Reassign ticket"
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

/** Delete a closed task. Hidden without `ticket:delete`. */
function TaskDelete({ orgSlug, task }: { orgSlug: string; task: Ticket }) {
  const canDelete = useHasPermission('ticket:delete', orgSlug)
  const navigate = useNavigate()
  const [confirm, setConfirm] = useState(false)
  const queryClient = useQueryClient()
  // Navigate before the refresh, so the deleted task is not read again.
  const remove = useMutation({
    mutationFn: () => deleteTicket(orgSlug, task.short_id),
    onSuccess: () => {
      navigate(ticketsPath())
      queryClient.removeQueries({
        queryKey: queryKeys.ticket(orgSlug, task.short_id),
      })
      for (const queryKey of [
        queryKeys.tickets(orgSlug),
        queryKeys.ticketsWaiting(orgSlug),
      ])
        void queryClient.invalidateQueries({ queryKey })
    },
  })
  if (!canDelete || task.status !== 'closed') return null
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        aria-label="Delete ticket"
        disabled={remove.isPending}
        onClick={() => setConfirm(true)}
        size="sm"
        title="Delete"
        variant="outline"
      >
        <Trash2 className="size-4" />
      </Button>
      <ConfirmDialog
        confirmLabel="Delete ticket"
        description="Imbi removes the ticket, its events, and its relations. The secret audit and the usage records stay. You cannot undo this."
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
  events: TicketEvent[]
  orgSlug: string
  task: Ticket
}) {
  const { data: agents } = useAgentList(orgSlug)
  const agent = agents?.find((a) => a.id === task.agent_id)
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
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
        <PriorityBadge priority={task.priority} />
        <Badge variant={statusVariant(task)}>{statusLabel(task)}</Badge>
        {task.assignee ? (
          <PersonStatusControls orgSlug={orgSlug} task={task} />
        ) : (
          <>
            <TaskControls orgSlug={orgSlug} task={task} />
            <TaskRetry orgSlug={orgSlug} task={task} />
          </>
        )}
        <HandOffControl orgSlug={orgSlug} task={task} />
        <TicketReopen orgSlug={orgSlug} task={task} />
        <TaskDelete orgSlug={orgSlug} task={task} />
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Fact>
          {task.assignee ? (
            <UserIdentity
              email={task.assignee}
              linkToProfile={false}
              size="small"
            />
          ) : agent ? (
            <Link
              className="text-primary font-medium hover:underline"
              to={agentsPath('manage', agent.slug)}
            >
              {agent.name}
            </Link>
          ) : (
            <span className="font-mono text-xs">{task.agent_id}</span>
          )}
          {task.agent_version && (
            <span className="text-tertiary font-mono text-xs">
              v{task.agent_version}
            </span>
          )}
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
        <TaskActivityCard
          elapsedMs={end - Date.parse(task.created_at)}
          events={events}
          task={task}
        />
        <TaskUsageCard events={events} task={task} />
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
                    current ? 'font-medium text-primary' : 'text-secondary',
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
 * `ticket:create`.
 */
function TaskRetry({ orgSlug, task }: { orgSlug: string; task: Ticket }) {
  const canCreate = useHasPermission('ticket:create', orgSlug)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  // Keep one key until a retry succeeds, so a repeat after a lost
  // response returns the first copy and does not make a second one.
  const [retryKey, setRetryKey] = useState(() => crypto.randomUUID())
  const retry = useMutation({
    mutationFn: () =>
      retryTicket(orgSlug, task.short_id, {
        idempotency_key: retryKey,
        note: note.trim() || null,
      }),
    onSuccess: (copy) => {
      setRetryKey(crypto.randomUUID())
      setOpen(false)
      setNote('')
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tickets(orgSlug),
      })
      navigate(ticketsPath(orgSlug, copy.short_id))
    },
  })
  // A 400 or 422 means the API did not make the task, so the note
  // can change. Any other error can come after the task was made.
  const rejected =
    retry.error instanceof ApiError &&
    (retry.error.status === 400 || retry.error.status === 422)
  if (!canCreate || !isFailed(task)) return null
  // A workflow's agent step made this task. The API refuses to retry
  // it: a copy would not belong to the run, so the run would not go on.
  const stepRunId = task.origin.workflow_run_id
  if (typeof stepRunId === 'string' && stepRunId) {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button
            aria-label="Retry ticket"
            size="sm"
            title="A workflow step made this ticket"
            variant="outline"
          >
            <RotateCcw className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-96">
          <p className="text-secondary text-sm" role="note">
            Step{' '}
            <span className="font-mono">
              {String(task.origin.node_key ?? '')}
            </span>{' '}
            of workflow run <span className="font-mono">{stepRunId}</span> made
            this ticket. A retry would not belong to the run, so the run would
            not continue. Start a new run of the workflow instead, for example
            with Retry run on the page of the run.
          </p>
        </PopoverContent>
      </Popover>
    )
  }
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <Button
          aria-label="Retry ticket"
          size="sm"
          title="Retry as a new ticket"
          variant="outline"
        >
          <RotateCcw className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-96 flex-col gap-3">
        <p className="text-secondary text-sm">
          Imbi makes a new ticket with the same agent and description, and adds
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

/**
 * The custom fields that the `Ticket` blueprints of the ticket declare,
 * editable with `ticket:manage`. A stored value that no blueprint
 * declares now stays hidden.
 */
function TicketCustomFields({
  editable,
  orgSlug,
  task,
}: {
  editable: boolean
  orgSlug: string
  task: Ticket
}) {
  const params = {
    label: task.labels,
    priority: task.priority,
    type: task.type,
  }
  const { data } = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => getTicketSchema(orgSlug, params, signal),
    queryKey: queryKeys.ticketSchema(orgSlug, params),
    staleTime: 60_000,
  })
  const update = useTicketMutation(
    orgSlug,
    task.short_id,
    (custom_fields: Record<string, unknown>) =>
      updateTicket(orgSlug, task.short_id, { custom_fields }),
  )
  const values = task.custom_fields
  const valueOf = useCallback((key: string) => values?.[key], [values])
  const sections = data?.sections ?? []
  if (!sections.some((s) => Object.keys(s.properties).length)) return null
  const pending = update.isPending && Object.keys(update.variables ?? {})[0]
  return (
    <Card className="p-5">
      <h3 className="text-overline text-tertiary mb-2 uppercase">
        Custom fields
      </h3>
      <BlueprintFields
        patch={(path, value) =>
          update
            .mutateAsync({ [path.slice(1)]: value })
            .then(() => undefined)
            .catch((err: Error) => {
              throw new Error(errorMessage(err))
            })
        }
        pendingPath={pending ? `/${pending}` : null}
        readOnly={!editable}
        sections={sections}
        valueOf={valueOf}
      />
    </Card>
  )
}

/**
 * Labels (each opens the tickets with it), the people in roles, and
 * the backlog place. Editable with `ticket:manage`.
 */
function TicketPeopleAndLabels({
  editable,
  onUpdate,
  orgSlug,
  pending,
  task,
}: {
  editable: boolean
  onUpdate: (body: TicketUpdate, onSuccess?: () => void) => void
  orgSlug: string
  pending: boolean
  task: Ticket
}) {
  const { isError: peopleError, people } = usePeople(orgSlug)
  const [roles, setRoles] = useState<null | ReturnType<typeof roleRows>>(null)
  const top = useTicketMutation(orgSlug, task.short_id, () =>
    rankTicket(orgSlug, task.short_id, null),
  )
  const roleList = Object.entries(task.roles)
  return (
    <Card className="flex flex-col gap-5 p-5">
      <div className="flex flex-col gap-2">
        <h3 className="text-overline text-tertiary uppercase">Labels</h3>
        {editable ? (
          <LabelInput
            disabled={pending}
            onChange={(labels) => onUpdate({ labels })}
            orgSlug={orgSlug}
            value={task.labels}
          />
        ) : null}
        {task.labels.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {task.labels.map((l) => (
              <LabelLink key={l} label={l} orgSlug={orgSlug} />
            ))}
          </div>
        ) : (
          !editable && <span className="text-tertiary text-sm">None</span>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-overline text-tertiary uppercase">Roles</h3>
          {editable && roles === null && (
            <Button
              className="ml-auto h-7 px-2 text-xs"
              onClick={() => setRoles(roleRows(task.roles))}
              size="sm"
              variant="ghost"
            >
              Edit
            </Button>
          )}
        </div>
        {roles !== null ? (
          <>
            <RolesEditor
              disabled={pending}
              loadError={peopleError}
              onChange={setRoles}
              people={people}
              rows={roles}
            />
            <div className="flex gap-2">
              <Button
                disabled={pending || roleErrors(roles).some((e) => !!e)}
                // The rows stay until the save succeeds, to retry.
                onClick={() =>
                  onUpdate({ roles: rolesOf(roles) }, () => setRoles(null))
                }
                size="sm"
              >
                Save roles
              </Button>
              <Button
                onClick={() => setRoles(null)}
                size="sm"
                variant="outline"
              >
                Cancel
              </Button>
            </div>
          </>
        ) : roleList.length ? (
          <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
            {roleList.map(([role, email]) => (
              <div className="contents" key={role}>
                <dt className="text-secondary font-mono text-[13px]">{role}</dt>
                <dd>
                  <UserIdentity email={email} size="small" />
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <span className="text-tertiary text-sm">
            None. Workflows can hand the ticket to the person in a role.
          </span>
        )}
      </div>
      {editable && BACKLOG.has(task.status) && (
        <div className="flex items-center gap-2">
          <h3 className="text-overline text-tertiary uppercase">Backlog</h3>
          <span className="text-tertiary text-xs">
            {task.backlog_rank == null ? 'Not ranked' : 'Ranked'}. Drag rows in
            the Queued group to reorder.
          </span>
          <Button
            className="ml-auto h-7 px-2 text-xs"
            disabled={top.isPending}
            onClick={() => top.mutate(undefined)}
            size="sm"
            variant="outline"
          >
            Move to top
          </Button>
        </div>
      )}
    </Card>
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
