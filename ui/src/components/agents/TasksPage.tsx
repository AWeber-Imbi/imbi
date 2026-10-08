import { useMemo, useState } from 'react'

import { Link, useParams } from 'react-router-dom'

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
import { cn } from '@/lib/utils'
import type { AgentTaskListItem, AgentTaskStatus } from '@/types'

import { agentsPath } from './agentsNav'
import { TaskDetail } from './TaskDetail'
import { groupTasks, statusLabel, statusVariant, TRIGGERS } from './taskEvents'
import { useAgentTasks } from './taskQueries'

const OPEN: AgentTaskStatus[] = ['blocked', 'running', 'paused', 'queued']

// ponytail: the inbox reads the newest 100 open and 25 closed tasks;
// page with the Link header when an org has more open work than that.
const OPEN_LIMIT = 100
const CLOSED_LIMIT = 25

const STATES: { label: string; slug: AgentTaskStatus }[] = [
  { label: 'Needs input', slug: 'blocked' },
  { label: 'Running', slug: 'running' },
  { label: 'Paused', slug: 'paused' },
  { label: 'Queued', slug: 'queued' },
  { label: 'Closed', slug: 'closed' },
]

/**
 * Agents > Tasks: the inbox in a resizable pane and the task in the URL
 * (`/agents/tasks/<short id>[/<tab>]`).
 */
export function TasksPage() {
  const { action: tab, slug: shortId } = useParams<{
    action?: string
    slug?: string
  }>()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('agent_task:read')
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
          <TaskInbox orgSlug={orgSlug} selected={shortId} />
        </Panel>
        <Separator className="hover:after:bg-amber-border focus-visible:after:bg-amber-border relative w-1.5 cursor-col-resize bg-transparent outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-(--ds-border-primary) after:transition-colors" />
        <Panel className="flex min-h-0 flex-col" id="detail" minSize="35%">
          {shortId ? (
            <TaskDetail
              key={shortId}
              orgSlug={orgSlug}
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
  const open = useAgentTasks(orgSlug, {
    limit: OPEN_LIMIT,
    mine,
    q,
    status: OPEN,
  })
  const closed = useAgentTasks(orgSlug, {
    limit: CLOSED_LIMIT,
    mine,
    q,
    status: ['closed'],
  })
  const tasks = useMemo(
    () => [...(open.data ?? []), ...(closed.data ?? [])],
    [open.data, closed.data],
  )
  const shown = tasks.filter(
    (t) =>
      (states.size === 0 || states.has(t.status)) &&
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
              </span>
            </h3>
            {group.tasks.map((task) => (
              <TaskRow
                active={task.short_id === selected}
                key={task.id}
                task={task}
              />
            ))}
          </section>
        ))}
      </div>
      <div className="border-tertiary text-tertiary shrink-0 border-t py-2 text-center text-xs">
        {shown.length} of {tasks.length} tasks
      </div>
    </>
  )
}

function TaskRow({
  active,
  task,
}: {
  active: boolean
  task: AgentTaskListItem
}) {
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
  const since =
    task.status === 'blocked'
      ? (task.blocked_since ?? task.updated_at)
      : task.status === 'closed'
        ? task.closed_at
        : task.created_at
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
      to={agentsPath('tasks', task.short_id)}
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
