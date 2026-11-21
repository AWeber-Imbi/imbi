import { Fragment, useState } from 'react'

import { Link, useLocation } from 'react-router-dom'

import { ChevronRight, FolderKanban, Workflow } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { EntityIcon } from '@/components/ui/entity-icon'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { cn } from '@/lib/utils'
import type { TicketListItem, TicketUnit, TicketUnitItem } from '@/types'

import { agentsPath, ticketsPath } from './agentsNav'
import {
  type InboxGroupId,
  statusLabel,
  statusVariant,
  TRIGGERS,
} from './taskEvents'
import { type FilterAgent, PersonMark } from './TaskFilterBar'
import { barClass, GROUP_SAYS, treeOf, unitTitle } from './taskUnits'

/** The child tickets a top-level ticket shows before "Show all". */
const CHILDREN_SHOWN = 2

/** The most bars a unit row draws, newest kept. */
const BARS_SHOWN = 24

export function ProjectMark({ icon }: { icon?: string }) {
  const className = 'mr-1 inline size-3 align-[-2px]'
  return icon ? (
    <EntityIcon className={className} icon={icon} />
  ) : (
    <FolderKanban aria-hidden className={className} />
  )
}

/**
 * A unit of work with more than one ticket: a header in the language of
 * a ticket row (title, workflow, latest activity; a bar per top-level
 * ticket, counts, and the representative ticket's badge, projects,
 * trigger, and owner), and when expanded, its tickets.
 */
export function TaskUnitRow({
  agents,
  expanded,
  group,
  onToggle,
  orgSlug,
  selectedId,
  task,
}: {
  agents: Map<string, FilterAgent>
  expanded: boolean
  group: InboxGroupId
  onToggle: () => void
  orgSlug: string
  selectedId?: string
  task: TicketListItem & { unit: TicketUnit }
}) {
  const { search } = useLocation()
  const unit = task.unit
  const title = unitTitle(unit, task.title)
  const trigger = TRIGGERS[task.origin.kind]
  const TriggerIcon = trigger.icon
  const label = statusLabel(task)
  const top = unit.tickets - unit.children
  const tree = treeOf(unit.items)
  const bars = tree.map((t) => t.top).slice(-BARS_SHOWN)
  const active = task.short_id.toUpperCase() === selectedId
  const name = (item: TicketUnitItem) =>
    item.assignee ?? agents.get(item.agent_id ?? '')?.name
  return (
    <div className="border-tertiary border-b">
      <div
        className={cn(
          'flex items-start gap-3 px-4 py-3 transition-colors',
          active ? 'bg-secondary' : 'hover:bg-secondary',
        )}
      >
        <button
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${title}`}
          className="bg-tertiary text-secondary hover:text-primary mt-px flex size-5 shrink-0 items-center justify-center rounded transition-colors"
          onClick={onToggle}
          type="button"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              'size-3 transition-transform',
              expanded && 'rotate-90',
            )}
          />
        </button>
        <Link
          aria-current={active ? 'page' : undefined}
          className="flex min-w-0 flex-1 flex-col gap-1"
          to={{ pathname: ticketsPath(orgSlug, task.short_id), search }}
        >
          <span className="flex items-baseline gap-2">
            <span
              className="min-w-0 flex-1 truncate text-sm font-medium"
              title={title}
            >
              {title}
              {unit.workflow_name && unit.workflow_name !== title && (
                <span className="text-tertiary ml-2 font-normal">
                  {unit.workflow_name}
                </span>
              )}
            </span>
            <RelativeTime
              className="text-tertiary shrink-0 font-mono text-xs"
              tooltip={false}
              value={unit.last_activity_at}
              variant="narrow"
            />
          </span>
          <span className="text-tertiary flex items-center gap-2 text-xs">
            <span aria-hidden className="flex shrink-0 items-center gap-0.5">
              {bars.map((item) => (
                <span
                  className={cn('h-3 w-1.5 rounded-xs', barClass(item))}
                  data-bar={item.short_id}
                  key={item.short_id}
                  title={`${item.short_id}: ${statusLabel(item)}`}
                />
              ))}
            </span>
            <span className="shrink-0">
              {top} {top === 1 ? 'task' : 'tasks'}
              {unit.children > 0 && ` · +${unit.children} child`}
            </span>
            {label !== GROUP_SAYS[group] && (
              <Badge className="shrink-0 py-0" variant={statusVariant(task)}>
                {label}
              </Badge>
            )}
            <span className="text-secondary min-w-0 flex-1 truncate font-mono">
              {task.projects.map((p, i) => (
                <Fragment key={p.project_id}>
                  {i > 0 && ', '}
                  <ProjectMark icon={task.project_icons?.[p.project_id]} />
                  {p.project_slug}
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
        </Link>
      </div>
      {expanded && (
        <ul aria-label={`Tickets of ${title}`} className="pb-2">
          {tree.map(({ descendants, top }) => (
            <UnitTree
              descendants={descendants}
              key={top.short_id}
              name={name}
              orgSlug={orgSlug}
              search={search}
              selectedId={selectedId}
              top={top}
            />
          ))}
          {unit.truncated && (
            <li className="text-tertiary py-1 pl-12 text-xs">
              Showing the first {unit.items.length} of {unit.tickets} tickets.
            </li>
          )}
          {unit.run_id && unit.workflow_slug && (
            <li className="pt-1 pl-12">
              <Link
                className="text-secondary hover:text-primary inline-flex items-center gap-1 text-xs underline-offset-4 hover:underline"
                to={agentsPath(
                  'workflows',
                  unit.workflow_slug,
                  'runs',
                  unit.run_id,
                )}
              >
                <Workflow aria-hidden className="size-3" />
                Open run
              </Link>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

function UnitTree({
  descendants,
  name,
  orgSlug,
  search,
  selectedId,
  top,
}: {
  descendants: TicketUnitItem[]
  name: (item: TicketUnitItem) => string | undefined
  orgSlug: string
  search: string
  selectedId?: string
  top: TicketUnitItem
}) {
  const [all, setAll] = useState(false)
  // The last children, and the selected one wherever it is.
  const shown = all
    ? descendants
    : descendants.filter(
        (d, i) =>
          i >= descendants.length - CHILDREN_SHOWN ||
          d.short_id.toUpperCase() === selectedId,
      )
  const row = (item: TicketUnitItem, depth: 0 | 1) => (
    <li key={item.short_id}>
      <Link
        aria-current={
          item.short_id.toUpperCase() === selectedId ? 'page' : undefined
        }
        className={cn(
          'flex items-center gap-2 py-1 pr-4 text-xs transition-colors',
          depth ? 'pl-16' : 'pl-12',
          item.short_id.toUpperCase() === selectedId
            ? 'bg-secondary'
            : 'hover:bg-secondary',
        )}
        to={{ pathname: ticketsPath(orgSlug, item.short_id), search }}
      >
        <span className="text-tertiary shrink-0 font-mono">
          {item.short_id}
        </span>
        <span className="min-w-0 flex-1 truncate" title={item.title}>
          {item.node_key && (
            <span className="text-tertiary mr-1.5 font-mono">
              {item.node_key}
            </span>
          )}
          {item.title}
        </span>
        {name(item) && (
          <span className="text-tertiary max-w-1/4 shrink-0 truncate">
            {name(item)}
          </span>
        )}
        <Badge className="shrink-0 py-0" variant={statusVariant(item)}>
          {statusLabel(item)}
        </Badge>
      </Link>
    </li>
  )
  return (
    <>
      {row(top, 0)}
      {descendants.length > shown.length && (
        <li>
          <button
            className="text-secondary hover:text-primary py-1 pl-16 text-xs underline-offset-4 hover:underline"
            onClick={() => setAll(true)}
            type="button"
          >
            Show all {descendants.length} child tasks
          </button>
        </li>
      )}
      {shown.map((item) => row(item, 1))}
    </>
  )
}
