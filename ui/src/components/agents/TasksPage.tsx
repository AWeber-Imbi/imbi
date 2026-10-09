import { useEffect, useMemo, useRef, useState } from 'react'

import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'

import { Inbox } from 'lucide-react'
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from 'react-resizable-panels'

import { Badge } from '@/components/ui/badge'
import { FilterPopover } from '@/components/ui/filter-popover'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'
import { cn } from '@/lib/utils'
import type { AgentTaskListItem, AgentTaskStatus } from '@/types'

import { agentsPath } from './agentsNav'
import { TaskDetail } from './TaskDetail'
import { groupTasks, statusLabel, statusVariant, TRIGGERS } from './taskEvents'
import { useAgentTaskPages } from './taskQueries'

const OPEN: AgentTaskStatus[] = ['blocked', 'running', 'paused', 'queued']

const STATES: { label: string; slug: AgentTaskStatus }[] = [
  { label: 'Needs input', slug: 'blocked' },
  { label: 'Running', slug: 'running' },
  { label: 'Paused', slug: 'paused' },
  { label: 'Queued', slug: 'queued' },
  { label: 'Closed', slug: 'closed' },
]

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
  const canRead = useHasPermission('agent_task:read')
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
    storage: typeof window === 'undefined' ? undefined : window.localStorage,
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
    <div
      style={{ height: 'calc(100vh - 4rem - var(--assistant-height, 64px))' }}
    >
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

function TaskInbox({
  orgSlug,
  selected,
}: {
  orgSlug: string
  selected?: string
}) {
  const [text, setText] = useState('')
  const [mine, setMine] = useState(false)
  const [states, setStates] = useState(new Set<string>())
  const [owners, setOwners] = useState(new Set<string>())
  const q = useDebouncedValue(text.trim(), 250) || undefined
  const open = useAgentTaskPages(orgSlug, { mine, q, status: OPEN })
  const closed = useAgentTaskPages(orgSlug, { mine, q, status: ['closed'] })
  // The API gives tasks newest first, but the open groups sort by other
  // fields (blocked_since), so a part of the open tasks can put a task in
  // the wrong place. Thus the inbox reads all of the open pages. The
  // closed group reads its next page when the end of the list comes into
  // view.
  const { fetchNextPage, hasNextPage, isFetching } = open
  useEffect(() => {
    if (hasNextPage && !isFetching) void fetchNextPage()
  }, [fetchNextPage, hasNextPage, isFetching])
  const { sentinelRef } = useInfiniteScroll({
    fetchNextPage: closed.fetchNextPage,
    hasNextPage: closed.hasNextPage && !open.hasNextPage,
    isFetchingNextPage: closed.isFetching,
  })
  const tasks = useMemo(
    () =>
      [...(open.data?.pages ?? []), ...(closed.data?.pages ?? [])].flatMap(
        (page) => page.entries,
      ),
    [open.data, closed.data],
  )
  const shown = tasks.filter(
    (t) =>
      (states.size === 0 ||
        states.has(t.status) ||
        (!!t.blocked_since && states.has('blocked'))) &&
      (owners.size === 0 || owners.has(t.owner)),
  )
  const groups = groupTasks(shown)
  const toggle = (set: Set<string>, value: string) => {
    const next = new Set(set)
    if (!next.delete(value)) next.add(value)
    return next
  }
  const ownerOptions = [...new Set(tasks.map((t) => t.owner))]
    .sort()
    .map((o) => ({ label: o, slug: o }))
  const loading = open.isLoading || closed.isLoading
  const more = open.hasNextPage || closed.hasNextPage
  const error = open.error ?? closed.error

  return (
    <>
      <div className="border-tertiary flex shrink-0 flex-col gap-2 border-b p-3">
        <Input
          aria-label="Filter tasks"
          className="h-8 text-sm"
          onChange={(e) => setText(e.target.value)}
          placeholder="Filter tasks, agents, projects"
          value={text}
        />
        <div className="flex items-center gap-2">
          <FilterPopover
            activeFilters={states}
            label="State"
            onClear={() => setStates(new Set())}
            onToggle={(s) => setStates(toggle(states, s))}
            options={STATES}
            variant="button"
          />
          <FilterPopover
            activeFilters={owners}
            label="Assignee"
            onClear={() => setOwners(new Set())}
            onToggle={(s) => setOwners(toggle(owners, s))}
            options={ownerOptions}
            variant="button"
          />
          <button
            aria-pressed={mine}
            className={cn(
              'ml-auto h-8 rounded-lg border border-tertiary px-2.5 text-xs',
              mine
                ? 'border-action bg-warning text-action'
                : 'bg-primary text-primary hover:border-secondary',
            )}
            onClick={() => setMine(!mine)}
            type="button"
          >
            My tasks
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="text-tertiary p-4 text-sm">Loading…</p>}
        {error && (
          <p className="text-danger p-4 text-sm" role="alert">
            Could not load tasks: {error.message}
          </p>
        )}
        {!loading && !error && groups.length === 0 && (
          <p className="text-tertiary p-6 text-center text-sm">
            {tasks.length === 0 && !q && !mine
              ? 'No tasks yet. Start one with Run on an agent.'
              : 'No tasks match.'}
          </p>
        )}
        {groups.map((group) => (
          <section aria-label={group.label} key={group.id}>
            <h3 className="border-tertiary bg-secondary text-overline text-tertiary flex justify-between border-b px-4 py-1.5 uppercase">
              <span>{group.label}</span>
              <span className="font-mono tabular-nums">
                {group.tasks.length}
                {(group.id === 'closed' ? closed : open).hasNextPage && '+'}
              </span>
            </h3>
            {group.tasks.map((task) => (
              <TaskRow
                active={task.short_id === selected}
                key={task.id}
                orgSlug={orgSlug}
                task={task}
              />
            ))}
          </section>
        ))}
        {more && (
          <p className="text-tertiary p-4 text-center text-sm">Loading…</p>
        )}
        <div ref={sentinelRef} />
      </div>
      <div className="border-tertiary text-tertiary shrink-0 border-t py-2 text-center text-xs">
        {shown.length} of {tasks.length}
        {more && '+'} tasks
      </div>
    </>
  )
}

function TaskRow({
  active,
  orgSlug,
  task,
}: {
  active: boolean
  orgSlug: string
  task: AgentTaskListItem
}) {
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
  const since =
    task.blocked_since ??
    (task.status === 'closed' ? task.closed_at : task.created_at)
  const label =
    task.status === 'running' && task.phase
      ? task.phase[0].toUpperCase() + task.phase.slice(1)
      : statusLabel(task)
  return (
    <Link
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex flex-col gap-1 border-b border-tertiary px-4 py-3 transition-colors',
        active ? 'bg-secondary' : 'hover:bg-secondary',
      )}
      to={agentsPath('tasks', orgSlug, task.short_id)}
    >
      <span className="flex items-center gap-2">
        <span className="text-tertiary font-mono text-xs">{task.short_id}</span>
        <Badge variant={statusVariant(task)}>{label}</Badge>
        <RelativeTime
          className="text-tertiary ml-auto font-mono text-xs"
          tooltip={false}
          value={since}
          variant="narrow"
        />
      </span>
      <span className="text-sm font-medium">{task.title}</span>
      <span className="flex items-center gap-2 text-xs">
        <span className="text-secondary truncate font-mono">
          {task.project_slug ?? ''}
        </span>
        <span className="text-tertiary ml-auto flex shrink-0 items-center gap-1">
          <TriggerIcon className="size-3" />
          {trigger.label}
        </span>
      </span>
    </Link>
  )
}
