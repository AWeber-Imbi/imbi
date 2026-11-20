import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'

import { useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  ChevronRight,
  CircleCheck,
  Clock,
  FolderKanban,
  Hand,
  Hourglass,
  Inbox,
  Loader,
  LocateFixed,
  type LucideIcon,
  Pause,
  Plus,
  RotateCw,
  Search,
} from 'lucide-react'
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from 'react-resizable-panels'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { getTicketPosition } from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import { IconTooltip } from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import { storage } from '@/lib/storage'
import { cn } from '@/lib/utils'
import type { TaskHighlight, TicketCounts, TicketListItem } from '@/types'

import { useAgentList } from './agentQueries'
import { ticketsPath } from './agentsNav'
import { NewTaskDialog } from './NewTaskDialog'
import { PriorityBadge } from './priority'
import { TaskDetail } from './TaskDetail'
import {
  INBOX_GROUPS,
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
import { TASK_PAGE, useTicketCounts, useTicketGroupPages } from './taskQueries'
import { SEARCH_MATCH, useMatchHighlight } from './taskSearch'
import { useStoredState } from './useStoredState'
import { useVirtualRows } from './virtualRows'

/**
 * A short id: an old link (`/agents/tasks/<short id>`) has no org.
 * It stays with the redirect in App.tsx.
 */
const SHORT_ID = /^T-\d+$/

/**
 * Tickets: the inbox in a resizable pane and the ticket in the URL
 * (`/tickets/<org slug>/<short id>[/<tab>]`). The org in the URL
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
  const { hash, search } = useLocation()
  const navigate = useNavigate()
  const { organizations, selectedOrganization, setSelectedOrganization } =
    useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('ticket:read', orgSlug)
  const urlOrg = organizations.find((o) => o.slug === taskOrg)
  useEffect(() => {
    if (urlOrg) setSelectedOrganization(urlOrg)
  }, [urlOrg, setSelectedOrganization])
  // A change to a different org in the header closes the task.
  const previousOrg = useRef(orgSlug)
  useEffect(() => {
    if (taskOrg && previousOrg.current === taskOrg && orgSlug !== taskOrg)
      navigate(ticketsPath())
    previousOrg.current = orgSlug
  }, [orgSlug, taskOrg, navigate])
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: 'imbi:tickets:split',
    panelIds: ['list', 'detail'],
    storage,
  })

  if (!orgSlug || !canRead) {
    return (
      <div className="text-tertiary p-8 text-center">
        {orgSlug
          ? 'You do not have permission to read tickets.'
          : 'Select an organization to see tickets.'}
      </div>
    )
  }

  // An old link without the org (ADR 0028).
  if (legacy) {
    const rest = [orgSlug, shortId!, ...(tab ? [tab] : [])]
    return <Navigate replace to={`${ticketsPath(...rest)}${search}${hash}`} />
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
        <Separator className="hover:after:bg-amber-border focus-visible:after:bg-amber-border relative z-20 -mx-0.75 w-1.5 cursor-col-resize bg-transparent outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-(--ds-border-primary) after:transition-colors" />
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
              Select a ticket.
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

function nonEmpty<T>(values: T[]) {
  return values.length ? values : undefined
}

const HEADER_HEIGHT = 29

type GroupInfo = (typeof INBOX_GROUPS)[number]
const ROW_HEIGHT = 72

type InboxRow =
  | { count: number; group: GroupInfo; kind: 'group' }
  | { group: InboxGroupId; index: number; kind: 'task' }

function GroupHeader({
  count,
  group,
  onToggle,
  open,
  pinned = false,
}: {
  count: number
  group: GroupInfo
  onToggle: () => void
  open: boolean
  pinned?: boolean
}) {
  return (
    <h3
      aria-hidden={pinned || undefined}
      className="border-tertiary bg-secondary text-overline text-tertiary border-b"
    >
      <button
        aria-expanded={open}
        className="hover:text-secondary flex w-full items-center justify-between px-4 py-1.5 uppercase transition-colors"
        onClick={onToggle}
        tabIndex={pinned ? -1 : undefined}
        type="button"
      >
        <span className="flex items-center gap-1.5">
          <ChevronRight
            aria-hidden
            className={cn('size-3 transition-transform', open && 'rotate-90')}
          />
          <GroupIcon id={group.id} />
          {group.label}
        </span>
        <span className="font-mono tabular-nums">{count}</span>
      </button>
    </h3>
  )
}

/**
 * The rows of the inbox: a header for each group that has tasks, then a
 * slot for each of its tasks unless the group is collapsed.
 */
function inboxRows(
  counts: TicketCounts | undefined,
  collapsed: InboxGroupId[],
): InboxRow[] {
  if (!counts) return []
  return INBOX_GROUPS.flatMap((group): InboxRow[] => {
    const count = counts[group.id]
    if (!count) return []
    const header: InboxRow = { count, group, kind: 'group' }
    if (collapsed.includes(group.id)) return [header]
    return [
      header,
      ...Array.from({ length: count }, (_, index) => ({
        group: group.id,
        index,
        kind: 'task' as const,
      })),
    ]
  })
}

function pageOf(row: { group: InboxGroupId; index: number }) {
  return `${row.group}:${Math.floor(row.index / TASK_PAGE)}`
}

function parseGroupList(raw: unknown): InboxGroupId[] | undefined {
  return Array.isArray(raw)
    ? INBOX_GROUPS.map((g) => g.id).filter((id) => raw.includes(id))
    : undefined
}

function rowKey(row: InboxRow | undefined) {
  if (!row) return ''
  return row.kind === 'group' ? row.group.id : `${row.group}:${row.index}`
}

/**
 * The header row that sticks at the top: the last one above `top`, and
 * how far the next header pushes it up. None while the header is in its
 * own place.
 */
function stickyHeader(
  headers: number[],
  starts: (index: number) => number,
  top: number,
): undefined | { index: number; push: number } {
  let current = -1
  let next = -1
  for (const i of headers) {
    if (starts(i) < top) current = i
    else {
      next = i
      break
    }
  }
  if (current < 0) return undefined
  const push = next < 0 ? 0 : Math.min(0, starts(next) - top - HEADER_HEIGHT)
  return { index: current, push }
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
  const [collapsed, setCollapsed] = useStoredState<InboxGroupId[]>(
    'imbi.tasks.collapsed',
    [],
    parseGroupList,
  )
  const listRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  useMatchHighlight(listRef, 'task-list-search')
  const canCreate = useHasPermission('ticket:create', orgSlug)
  const q = useDebouncedValue(text.trim(), 250) || undefined
  const params = {
    agent_id: nonEmpty(filters.agents),
    mine: filters.assignees.includes(ME),
    owner: nonEmpty(filters.assignees.filter((a) => a !== ME)),
    q,
    status: nonEmpty(filters.states),
  }
  const paramsKey = JSON.stringify(params)
  const shownParams = useRef(paramsKey)
  useEffect(() => {
    if (shownParams.current === paramsKey) return
    shownParams.current = paramsKey
    if (listRef.current) listRef.current.scrollTop = 0
  }, [paramsKey])
  const counts = useTicketCounts(orgSlug, params)
  const rows = useMemo(
    () => inboxRows(counts.data, collapsed),
    [counts.data, collapsed],
  )
  const getItemKey = useCallback((i: number) => rowKey(rows[i]), [rows])
  const virtualizer = useVirtualRows({
    count: rows.length,
    estimateSize: (i) =>
      rows[i]?.kind === 'group' ? HEADER_HEIGHT : ROW_HEIGHT,
    getItemKey,
    overscan: 12,
    scroller: listRef,
  })
  const items = virtualizer.getVirtualItems()
  const [revealing, setRevealing] = useState<{
    group: InboxGroupId
    index: number
    smooth: boolean
  }>()
  const revealRequest = useRef(0)
  const revealScope = useRef([paramsKey, selected])
  useEffect(() => {
    const [shownKey, shownSelected] = revealScope.current
    if (shownKey === paramsKey && shownSelected === selected) return
    revealScope.current = [paramsKey, selected]
    revealRequest.current += 1
    setRevealing(undefined)
  }, [paramsKey, selected])
  useEffect(() => {
    if (!revealing) return
    const at = rows.findIndex(
      (r) =>
        r.kind === 'task' &&
        r.group === revealing.group &&
        r.index === revealing.index,
    )
    if (at < 0) {
      if (counts.data && !collapsed.includes(revealing.group))
        setRevealing(undefined)
      return
    }
    setRevealing(undefined)
    virtualizer.scrollToIndex(at, {
      align: 'center',
      behavior:
        revealing.smooth &&
        !window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'smooth'
          : 'auto',
    })
  }, [collapsed, counts.data, revealing, rows, virtualizer])
  const scrollTop = useScrollTop(listRef)
  const headers = useMemo(
    () => rows.flatMap((row, i) => (row.kind === 'group' ? [i] : [])),
    [rows],
  )
  const sticky = stickyHeader(
    headers,
    (i) => virtualizer.measurementsCache[i]?.start ?? 0,
    scrollTop,
  )
  const stickyRow = sticky && rows[sticky.index]
  const stuck =
    sticky && stickyRow?.kind === 'group'
      ? { ...sticky, row: stickyRow }
      : undefined
  const pageNames = [
    ...new Set(
      items.flatMap((item) => {
        const row = rows[item.index]
        return row?.kind === 'task' ? [pageOf(row)] : []
      }),
    ),
  ]
  const pages = useTicketGroupPages(orgSlug, params, pageNames)
  const loaded = new Map(pageNames.map((name, i) => [name, pages[i]?.data]))
  const tasks = pages.flatMap((p) => p.data ?? [])
  const agentList = useAgentList(orgSlug)
  const { user } = useAuth()
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
  const total = counts.data
    ? Object.values(counts.data).reduce((sum, n) => sum + n, 0)
    : 0
  const failed = [counts, ...pages].filter((r) => r.error)
  const error = failed[0]?.error
  const retrying = failed.some((r) => r.isFetching)
  const retry = () => {
    for (const result of failed) void result.refetch()
  }
  const toggle = (id: InboxGroupId) =>
    setCollapsed(
      collapsed.includes(id)
        ? collapsed.filter((g) => g !== id)
        : [...collapsed, id],
    )
  const selectedId = selected?.toUpperCase()
  const viewTop = scrollTop + (stuck ? HEADER_HEIGHT + stuck.push : 0)
  const viewBottom = scrollTop + (virtualizer.scrollRect?.height ?? 0)
  const selectedInView = items.some((item) => {
    const row = rows[item.index]
    return (
      row?.kind === 'task' &&
      loaded
        .get(pageOf(row))
        ?.[row.index % TASK_PAGE]?.short_id.toUpperCase() === selectedId &&
      item.start >= viewTop &&
      item.end <= viewBottom
    )
  })
  const reveal = async (onLoad = false) => {
    if (!selected) return
    const request = ++revealRequest.current
    try {
      const at = await getTicketPosition(orgSlug, selected, params)
      const { group } = at
      const offset = Math.floor(at.index / TASK_PAGE) * TASK_PAGE
      await Promise.all([
        counts.refetch(),
        queryClient.refetchQueries({
          exact: true,
          queryKey: queryKeys.tickets(orgSlug, { ...params, group, offset }),
        }),
      ])
      if (request !== revealRequest.current) return
      setCollapsed((current) =>
        current.includes(group) ? current.filter((g) => g !== group) : current,
      )
      setRevealing({ ...at, smooth: !onLoad })
    } catch (err) {
      if (onLoad || request !== revealRequest.current) return
      toast.error(
        err instanceof ApiError && err.status === 404
          ? `The filters hide ${selected}.`
          : `Could not find ${selected} in the list.`,
      )
    }
  }
  const revealOnLoad = useRef(selected !== undefined)
  useEffect(() => {
    if (!revealOnLoad.current) return
    revealOnLoad.current = false
    void reveal(true)
  })
  // A header that collapses its group from the top keeps its place.
  const toggleSticky = (index: number, id: InboxGroupId) => {
    toggle(id)
    requestAnimationFrame(() =>
      virtualizer.scrollToIndex(index, { align: 'start' }),
    )
  }

  return (
    <>
      <TaskFilterBar
        action={
          <>
            <IconTooltip label="Reveal in list">
              <Button
                aria-label="Reveal in list"
                className="border-input size-8 shrink-0"
                disabled={!selected || selectedInView}
                onClick={() => void reveal()}
                size="icon"
                variant="outline"
              >
                <LocateFixed />
              </Button>
            </IconTooltip>
            <IconTooltip label="Waiting on me">
              <Button
                asChild
                className="border-input size-8 shrink-0"
                size="icon"
                variant="outline"
              >
                <Link aria-label="Waiting on me" to={ticketsPath('waiting')}>
                  <Hourglass />
                </Link>
              </Button>
            </IconTooltip>
            {canCreate && (
              <IconTooltip label="New ticket">
                <Button
                  aria-label="New ticket"
                  className="border-input size-8 shrink-0"
                  onClick={() => setCreating(true)}
                  size="icon"
                  variant="outline"
                >
                  <Plus />
                </Button>
              </IconTooltip>
            )}
          </>
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
              aria-label="Filter tickets"
              className="h-8 rounded-r-none pl-8 text-sm"
              onChange={(e) => setText(e.target.value)}
              placeholder="Search tickets"
              value={text}
            />
          </div>
        }
      />
      {error && (
        <Alert className="m-3" title="Could not load tickets" variant="danger">
          <div className="flex items-center justify-between gap-3">
            <span className="text-secondary min-w-0 truncate">
              {error.message}
            </span>
            <Button
              className="shrink-0"
              disabled={retrying}
              onClick={retry}
              size="sm"
              variant="outline"
            >
              <RotateCw
                className={cn(retrying && 'animate-spin')}
                data-icon="inline-start"
              />
              Retry
            </Button>
          </div>
        </Alert>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto" ref={listRef}>
        {counts.isLoading && (
          <div aria-busy aria-label="Loading tickets">
            {Array.from({ length: 6 }, (_, i) => (
              <TaskSlot key={i} />
            ))}
          </div>
        )}
        {counts.data && !error && total === 0 && (
          <p className="text-tertiary p-6 text-center text-sm">
            {!q && !filtered
              ? canCreate
                ? 'No tickets yet. Create one with New ticket.'
                : 'No tickets yet.'
              : 'No tickets match.'}
          </p>
        )}
        <div
          className="relative"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {stuck && (
            <div className="sticky top-0 z-10 h-0" data-sticky="">
              <div style={{ transform: `translateY(${stuck.push}px)` }}>
                <GroupHeader
                  count={stuck.row.count}
                  group={stuck.row.group}
                  onToggle={() => toggleSticky(stuck.index, stuck.row.group.id)}
                  open={!collapsed.includes(stuck.row.group.id)}
                  pinned={items.some((item) => item.index === stuck.index)}
                />
              </div>
            </div>
          )}
          {items.map((item) => {
            const row = rows[item.index]
            if (!row) return null
            const task =
              row.kind === 'task'
                ? loaded.get(pageOf(row))?.[row.index % TASK_PAGE]
                : undefined
            return (
              <div
                className="absolute inset-x-0 top-0"
                data-index={item.index}
                key={item.key}
                ref={virtualizer.measureElement}
                style={{ transform: `translateY(${item.start}px)` }}
              >
                {row.kind === 'group' ? (
                  <GroupHeader
                    count={row.count}
                    group={row.group}
                    onToggle={() => toggle(row.group.id)}
                    open={!collapsed.includes(row.group.id)}
                  />
                ) : task ? (
                  <TaskRow
                    active={task.short_id.toUpperCase() === selectedId}
                    agent={agentsById.get(task.agent_id ?? '')}
                    group={row.group}
                    orgSlug={orgSlug}
                    task={task}
                  />
                ) : (
                  <TaskSlot />
                )}
              </div>
            )
          })}
        </div>
      </div>
      {counts.data && (
        <div className="border-tertiary text-tertiary shrink-0 border-t py-2 text-center text-xs">
          {total} {total === 1 ? 'ticket' : 'tickets'}
        </div>
      )}
      <NewTaskDialog isOpen={creating} onClose={() => setCreating(false)} />
    </>
  )
}

function TaskSlot() {
  return (
    <div className="border-tertiary flex h-18 items-start gap-3 border-b px-4 py-3">
      <Sk h={20} r={4} w={20} />
      <div className="flex flex-1 flex-col gap-2.5 pt-1">
        <Sk line w="70%" />
        <Sk line w="45%" />
      </div>
    </div>
  )
}

function useScrollTop(ref: React.RefObject<HTMLElement | null>) {
  const [top, setTop] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onScroll = () => setTop(el.scrollTop)
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [ref])
  return top
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
  task: TicketListItem
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
      to={{ pathname: ticketsPath(orgSlug, task.short_id), search }}
    >
      <span
        className="mt-px flex shrink-0"
        title={task.assignee ?? agent?.name}
      >
        {task.assignee ? (
          <PersonMark email={task.assignee} />
        ) : agent ? (
          <AgentMark agent={agent} />
        ) : (
          <span
            aria-hidden
            className="bg-tertiary text-secondary flex size-5 items-center justify-center rounded"
          >
            <Bot className="size-3" />
          </span>
        )}
        {task.assignee ? (
          <span className="sr-only">Assigned to {task.assignee}</span>
        ) : (
          agent && !agentMatch && <span className="sr-only">{agent.name}</span>
        )}
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
          <PriorityBadge priority={task.priority} />
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
          <span className="sr-only">Owned by {task.owner}</span>
        </span>
      </span>
    </Link>
  )
}

/**
 * The owners of the tasks seen so far, so that the Assignee list keeps
 * them when a filter hides their tasks. The API has no list of them.
 */
function useSeenOwners(tasks: TicketListItem[], assignees: string[]) {
  const [seen, setSeen] = useState<string[]>([])
  useEffect(() => {
    const next = new Set(seen)
    for (const t of tasks) next.add(t.owner)
    for (const a of assignees) if (a !== ME) next.add(a)
    if (next.size > seen.length) setSeen([...next].sort())
  }, [assignees, seen, tasks])
  return seen
}
