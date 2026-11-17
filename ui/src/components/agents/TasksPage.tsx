import { Fragment, useEffect, useMemo, useRef, useState } from 'react'

import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'

import {
  Bot,
  CircleCheck,
  Clock,
  FolderKanban,
  Hand,
  Inbox,
  Loader,
  type LucideIcon,
  Pause,
  Plus,
  Search,
} from 'lucide-react'
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from 'react-resizable-panels'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { IconTooltip } from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'
import { storage } from '@/lib/storage'
import { cn } from '@/lib/utils'
import type { AgentTaskListItem, AgentTaskStatus, TaskHighlight } from '@/types'

import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'
import { NewTaskDialog } from './NewTaskDialog'
import { TaskDetail } from './TaskDetail'
import {
  groupTasks,
  type InboxGroupId,
  statusLabel,
  statusVariant,
  TRIGGERS,
} from './taskEvents'
import {
  AgentMark,
  type FilterAgent,
  PersonMark,
  TaskFilterBar,
} from './TaskFilterBar'
import { activeCount, ME, useTaskFilters } from './taskFilters'
import { useAgentTaskPages } from './taskQueries'
import { SEARCH_MATCH, useMatchHighlight } from './taskSearch'

const OPEN: AgentTaskStatus[] = ['blocked', 'running', 'paused', 'queued']

/** A short id: an old link (`/agents/tasks/<short id>`) has no org. */
const SHORT_ID = /^T-\d+$/

/**
 * Agents > Tasks: the inbox in a resizable pane and the task in the URL
 * (`/agents/tasks/<org slug>/<short id>[/<tab>]`). The org in the URL
 * becomes the selected org. An old link without the org goes to the
 * selected org.
 */
export function TasksPage() {
  const params = useParams<{
    action?: string
    slug?: string
    tab?: string
  }>()
  const legacy = SHORT_ID.test(params.slug ?? '')
  const taskOrg = legacy ? undefined : params.slug
  const shortId = legacy ? params.slug : params.action
  const tab = legacy ? params.action : params.tab
  const navigate = useNavigate()
  const { organizations, selectedOrganization, setSelectedOrganization } =
    useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('agent_task:read', orgSlug)
  const urlOrg = organizations.find((o) => o.slug === taskOrg)
  useEffect(() => {
    if (urlOrg) setSelectedOrganization(urlOrg)
  }, [urlOrg, setSelectedOrganization])
  // A change to a different org in the header closes the task.
  const previousOrg = useRef(orgSlug)
  useEffect(() => {
    if (taskOrg && previousOrg.current === taskOrg && orgSlug !== taskOrg)
      navigate(agentsPath('tasks'))
    previousOrg.current = orgSlug
  }, [orgSlug, taskOrg, navigate])
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: 'imbi:agent-tasks:split',
    panelIds: ['list', 'detail'],
    storage,
  })

  if (!orgSlug || !canRead) {
    return (
      <div className="text-tertiary p-8 text-center">
        {orgSlug
          ? 'You do not have permission to read agent tasks.'
          : 'Select an organization to see agent tasks.'}
      </div>
    )
  }

  if (legacy) {
    const rest = [orgSlug, shortId!, ...(tab ? [tab] : [])]
    return <Navigate replace to={agentsPath('tasks', ...rest)} />
  }

  if (taskOrg && !urlOrg) {
    return (
      <div className="text-tertiary p-8 text-center">
        You are not a member of the organization {taskOrg}.
      </div>
    )
  }

  // The Group sets its own height to 100%, so a wrapper sets the height:
  // the viewport less the header and the assistant bar.
  return (
    <div style={{ height: 'calc(100vh - 4rem)' }}>
      <Group
        defaultLayout={defaultLayout}
        onLayoutChanged={onLayoutChanged}
        orientation="horizontal"
      >
        <Panel
          className="border-tertiary bg-primary flex min-h-0 flex-col"
          defaultSize="32%"
          id="list"
          maxSize="55%"
          minSize="20%"
        >
          <TaskInbox
            key={orgSlug}
            orgSlug={orgSlug}
            selected={taskOrg === orgSlug ? shortId : undefined}
          />
        </Panel>
        <Separator className="hover:after:bg-amber-border focus-visible:after:bg-amber-border relative w-1.5 cursor-col-resize bg-transparent outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-(--ds-border-primary) after:transition-colors" />
        <Panel className="flex min-h-0 flex-col" id="detail" minSize="35%">
          {taskOrg && shortId ? (
            <TaskDetail
              key={`${taskOrg}:${shortId}`}
              orgSlug={taskOrg}
              shortId={shortId}
              tab={tab}
            />
          ) : (
            <div className="text-tertiary flex flex-1 flex-col items-center justify-center gap-2 text-sm">
              <Inbox className="size-8" />
              Select a task.
            </div>
          )}
        </Panel>
      </Group>
    </div>
  )
}

function Marked({
  parts,
  text,
}: {
  parts?: TaskHighlight['parts']
  text: string
}) {
  if (!parts) return text
  let at = 0
  return parts.map((part) => {
    const key = at
    at += part.text.length
    return part.match ? (
      <span key={key} {...{ [SEARCH_MATCH]: '' }}>
        {part.text}
      </span>
    ) : (
      <Fragment key={key}>{part.text}</Fragment>
    )
  })
}

function nonEmpty(values: string[]) {
  return values.length ? values : undefined
}

function TaskInbox({
  orgSlug,
  selected,
}: {
  orgSlug: string
  selected?: string
}) {
  const [text, setText] = useState('')
  const [filters, setFilters] = useTaskFilters()
  const [creating, setCreating] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  useMatchHighlight(listRef, 'task-list-search')
  const canCreate = useHasPermission('agent_task:create', orgSlug)
  const q = useDebouncedValue(text.trim(), 250) || undefined
  // Every open page is read, so the open states filter here; the
  // closed tasks are paged, so only the server can filter them.
  const openStates = filters.states.filter((s) => s !== 'closed')
  const scope = {
    agent_id: nonEmpty(filters.agents),
    mine: filters.assignees.includes(ME),
    owner: nonEmpty(filters.assignees.filter((a) => a !== ME)),
    q,
  }
  // A query that a filter turns off still holds its cached pages, so
  // nothing below reads it.
  const wantOpen = filters.states.length === 0 || openStates.length > 0
  const wantClosed =
    filters.states.length === 0 || filters.states.includes('closed')
  const open = useAgentTaskPages(orgSlug, { ...scope, status: OPEN }, wantOpen)
  const closed = useAgentTaskPages(
    orgSlug,
    { ...scope, status: ['closed'] },
    wantClosed,
  )
  const openMore = wantOpen && open.hasNextPage
  const closedMore = wantClosed && closed.hasNextPage
  const agentList = useAgentList(orgSlug)
  const { user } = useAuth()
  // The API gives tasks newest first, but the open groups sort by other
  // fields (blocked_since), so a part of the open tasks can put a task in
  // the wrong place. Thus the inbox reads all of the open pages. The
  // closed group reads its next page when the end of the list comes into
  // view. After a failed page, only the Retry button reads it again.
  const { fetchNextPage, hasNextPage, isFetching, isFetchNextPageError } = open
  useEffect(() => {
    if (wantOpen && hasNextPage && !isFetching && !isFetchNextPageError)
      void fetchNextPage()
  }, [fetchNextPage, hasNextPage, isFetching, isFetchNextPageError, wantOpen])
  const { sentinelRef } = useInfiniteScroll({
    fetchNextPage: closed.fetchNextPage,
    hasNextPage: closedMore && !openMore && !closed.isFetchNextPageError,
    isFetchingNextPage: closed.isFetching,
  })
  const tasks = useMemo(
    () =>
      [
        ...((wantOpen && open.data?.pages) || []),
        ...((wantClosed && closed.data?.pages) || []),
      ].flatMap((page) => page.entries),
    [open.data, closed.data, wantOpen, wantClosed],
  )
  const shown =
    openStates.length === 0
      ? tasks
      : tasks.filter(
          (t) =>
            t.status === 'closed' ||
            openStates.includes(t.status) ||
            (!!t.blocked_since && openStates.includes('blocked')),
        )
  const groups = groupTasks(shown)
  const owners = useSeenOwners(tasks, filters.assignees)
  const agents = useMemo(
    () =>
      (agentList.data ?? [])
        .map((a) => ({ icon: a.icon, id: a.id, name: a.name }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [agentList.data],
  )
  const agentsById = useMemo(
    () => new Map(agents.map((a) => [a.id, a])),
    [agents],
  )
  const filtered = activeCount(filters) > 0
  const loading = open.isLoading || closed.isLoading
  const more = openMore || closedMore
  const openError = wantOpen ? open.error : null
  const error = openError ?? (wantClosed ? closed.error : null)
  const failed = openError ? open : closed
  const retry = () =>
    void (failed.isFetchNextPageError
      ? failed.fetchNextPage()
      : failed.refetch())

  return (
    <>
      <TaskFilterBar
        action={
          canCreate && (
            <IconTooltip label="New task">
              <Button
                aria-label="New task"
                className="border-input size-8 shrink-0"
                onClick={() => setCreating(true)}
                size="icon"
                variant="outline"
              >
                <Plus />
              </Button>
            </IconTooltip>
          )
        }
        agents={agents}
        filters={filters}
        me={user?.email}
        onChange={setFilters}
        owners={owners}
        search={
          <div className="relative min-w-0 flex-1">
            <Search className="text-tertiary pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
            <Input
              aria-label="Filter tasks"
              className="h-8 rounded-r-none pl-8 text-sm"
              onChange={(e) => setText(e.target.value)}
              placeholder="Search tasks"
              value={text}
            />
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto" ref={listRef}>
        {loading && <p className="text-tertiary p-4 text-sm">Loading…</p>}
        {error && (
          <p className="text-danger p-4 text-sm" role="alert">
            Could not load tasks: {error.message}{' '}
            <button className="underline" onClick={retry} type="button">
              Retry
            </button>
          </p>
        )}
        {!loading && !error && groups.length === 0 && (
          <p className="text-tertiary p-6 text-center text-sm">
            {tasks.length === 0 && !q && !filtered
              ? canCreate
                ? 'No tasks yet. Create one with New task.'
                : 'No tasks yet.'
              : 'No tasks match.'}
          </p>
        )}
        {groups.map((group) => (
          <section aria-label={group.label} key={group.id}>
            <h3 className="border-tertiary bg-secondary text-overline text-tertiary flex justify-between border-b px-4 py-1.5 uppercase">
              <span className="flex items-center gap-1.5">
                <GroupIcon id={group.id} />
                {group.label}
              </span>
              <span className="font-mono tabular-nums">
                {group.tasks.length}
                {(group.id === 'closed' ? closedMore : openMore) && '+'}
              </span>
            </h3>
            {group.tasks.map((task) => (
              <TaskRow
                active={task.short_id === selected}
                agent={agentsById.get(task.agent_id)}
                group={group.id}
                key={task.id}
                orgSlug={orgSlug}
                task={task}
              />
            ))}
          </section>
        ))}
        {more && !error && (
          <p className="text-tertiary p-4 text-center text-sm">Loading…</p>
        )}
        <div ref={sentinelRef} />
      </div>
      <div className="border-tertiary text-tertiary shrink-0 border-t py-2 text-center text-xs">
        {shown.length}
        {more && '+'} {shown.length === 1 && !more ? 'task' : 'tasks'}
      </div>
      <NewTaskDialog isOpen={creating} onClose={() => setCreating(false)} />
    </>
  )
}

const GROUP_ICONS: Record<InboxGroupId, LucideIcon> = {
  closed: CircleCheck,
  input: Hand,
  paused: Pause,
  queued: Clock,
  running: Loader,
}

function GroupIcon({ id }: { id: InboxGroupId }) {
  const Icon = GROUP_ICONS[id]
  return <Icon aria-hidden className="size-3" />
}

function ProjectMark({ icon }: { icon?: string }) {
  const className = 'mr-1 inline size-3 align-[-2px]'
  return icon ? (
    <EntityIcon className={className} icon={icon} />
  ) : (
    <FolderKanban aria-hidden className={className} />
  )
}

/** The status words that the group header already says. */
const GROUP_SAYS: Partial<Record<InboxGroupId, string>> = {
  input: 'Needs input',
  paused: 'Paused',
  queued: 'Queued',
  running: 'Running',
}

function TaskRow({
  active,
  agent,
  group,
  orgSlug,
  task,
}: {
  active: boolean
  agent?: FilterAgent
  group: InboxGroupId
  orgSlug: string
  task: AgentTaskListItem
}) {
  const { search } = useLocation()
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
  const since =
    task.blocked_since ??
    (task.status === 'closed' ? task.closed_at : task.created_at)
  const label =
    task.status === 'running' && task.phase
      ? task.phase[0].toUpperCase() + task.phase.slice(1)
      : statusLabel(task)
  const marked = (field: TaskHighlight['field'], id?: string) =>
    task.highlights?.find(
      (h) => h.field === field && (id === undefined || h.id === id),
    )?.parts
  const agentMatch = marked('agent')
  const projects = task.projects
    .map((p) => ({ ...p, parts: marked('project', p.project_id) }))
    .sort((a, b) => Number(!!b.parts) - Number(!!a.parts))
  return (
    <Link
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-start gap-3 border-b border-tertiary px-4 py-3 transition-colors',
        active ? 'bg-secondary' : 'hover:bg-secondary',
      )}
      to={{ pathname: agentsPath('tasks', orgSlug, task.short_id), search }}
    >
      <span className="mt-px flex shrink-0" title={agent?.name}>
        {agent ? (
          <AgentMark agent={agent} />
        ) : (
          <span
            aria-hidden
            className="bg-tertiary text-secondary flex size-5 items-center justify-center rounded"
          >
            <Bot className="size-3" />
          </span>
        )}
        {agent && !agentMatch && <span className="sr-only">{agent.name}</span>}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex items-baseline gap-2">
          <span
            className="min-w-0 flex-1 truncate text-sm font-medium"
            title={task.title}
          >
            <Marked parts={marked('title')} text={task.title} />
          </span>
          <RelativeTime
            className="text-tertiary shrink-0 font-mono text-xs"
            tooltip={false}
            value={since}
            variant="narrow"
          />
        </span>
        <span className="text-tertiary flex items-center gap-2 text-xs">
          <span className="shrink-0 font-mono">
            <Marked parts={marked('short_id')} text={task.short_id} />
          </span>
          {label !== GROUP_SAYS[group] && (
            <Badge className="shrink-0 py-0" variant={statusVariant(task)}>
              {label}
            </Badge>
          )}
          {agentMatch && (
            <span className="text-secondary max-w-1/2 shrink-0 truncate">
              <Marked parts={agentMatch} text="" />
            </span>
          )}
          <span className="text-secondary min-w-0 flex-1 truncate font-mono">
            {projects.map((p, i) => (
              <Fragment key={p.project_id}>
                {i > 0 && ', '}
                <ProjectMark icon={task.project_icons?.[p.project_id]} />
                <Marked parts={p.parts} text={p.project_slug} />
              </Fragment>
            ))}
          </span>
          <span className="flex shrink-0" title={trigger.label}>
            <TriggerIcon aria-hidden className="size-3" />
            <span className="sr-only">{trigger.label}</span>
          </span>
          <PersonMark email={task.owner} title={task.owner} />
          <span className="sr-only">Assigned to {task.owner}</span>
        </span>
      </span>
    </Link>
  )
}

/**
 * The owners of the tasks seen so far, so that the Assignee list keeps
 * them when a filter hides their tasks. The API has no list of them.
 */
function useSeenOwners(tasks: AgentTaskListItem[], assignees: string[]) {
  const [seen, setSeen] = useState<string[]>([])
  useEffect(() => {
    const next = new Set(seen)
    for (const t of tasks) next.add(t.owner)
    for (const a of assignees) if (a !== ME) next.add(a)
    if (next.size > seen.length) setSeen([...next].sort())
  }, [assignees, seen, tasks])
  return seen
}
