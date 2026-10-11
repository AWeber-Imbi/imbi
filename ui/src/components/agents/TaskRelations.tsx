import { type ReactNode, useState } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { Box, ChevronRight, Link2, Trash2 } from 'lucide-react'

import {
  listAgentTasks,
  setAgentTaskDependency,
  setAgentTaskProject,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskRelated } from '@/types'

import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'
import { statusLabel, statusVariant } from './taskEvents'
import {
  errorMessage,
  useAgentTaskProjects,
  useAgentTaskRelationMutation,
  useAgentTaskRelations,
} from './taskQueries'

/**
 * The kinds of a relation, as this task reads them. One dependency row
 * reads two ways: "this task requires T-5" is "this task is blocked by
 * T-5". Parent and child come from a `task` origin (delegation).
 */
const KINDS = {
  blocked_by: { label: 'Blocked by', requires: true },
  blocks: { label: 'Blocks', requires: false },
  required_by: { label: 'Required by', requires: false },
  requires: { label: 'Requires', requires: true },
} as const

type LinkKind = keyof typeof KINDS

const LINK_KINDS: LinkKind[] = [
  'requires',
  'required_by',
  'blocks',
  'blocked_by',
]

interface Row {
  alias: string
  kind: string
  /** The dependency `[dependent, prerequisite]`; none for delegation. */
  link?: [string, string]
  task: AgentTaskRelated
  tone: 'accent' | 'info' | 'neutral'
}

/** The primary project and the associated projects of the task. */
export function AssociatedProjectsTab({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: AgentTask
}) {
  const canManage = useHasPermission('agent_task:manage')
  const projects = useAgentTaskProjects(orgSlug, task.short_id)
  const [open, setOpen] = useState(false)
  const unlink = useAgentTaskRelationMutation(orgSlug, (projectId: string) =>
    setAgentTaskProject(orgSlug, task.short_id, projectId, false),
  )
  // An archived task is sealed: its projects cannot change.
  const editable = canManage && !task.log_archived_at
  return (
    <div>
      <PanelHeader
        action={
          editable && (
            <Button onClick={() => setOpen(true)} size="sm" variant="outline">
              Link project
            </Button>
          )
        }
      >
        Projects this task reads from or writes to
      </PanelHeader>
      {(projects.error ?? unlink.error) && (
        <p className="text-danger px-6 py-3 text-sm" role="alert">
          {errorMessage((projects.error ?? unlink.error)!)}
        </p>
      )}
      <ul aria-label="Associated projects">
        {(projects.data ?? []).map((p) => (
          <li
            className="border-tertiary flex items-center gap-4 border-b px-6 py-3"
            key={p.project_id}
          >
            <Box className="text-tertiary size-4 shrink-0" />
            <span
              className={cn(
                'min-w-44 max-w-72 truncate text-sm font-medium',
                !p.available && 'text-tertiary',
              )}
            >
              {p.name ?? p.project_slug}
            </span>
            <span className="text-tertiary min-w-0 flex-1 truncate font-mono text-xs">
              {p.project_slug}
            </span>
            {p.primary && <Badge variant="neutral">Primary</Badge>}
            {!p.available && (
              <span className="text-tertiary text-xs">No longer available</span>
            )}
            {editable && !p.primary ? (
              <button
                aria-label={`Remove project ${p.project_slug}`}
                className="text-tertiary hover:text-danger flex size-8 shrink-0 items-center justify-center rounded-md transition-colors"
                disabled={unlink.isPending}
                onClick={() => unlink.mutate(p.project_id)}
                title="Remove project"
                type="button"
              >
                <Trash2 className="size-3.5" />
              </button>
            ) : (
              editable && <span className="size-8 shrink-0" />
            )}
            {p.available ? (
              <Link
                aria-label={`Open project ${p.project_slug}`}
                className="text-tertiary hover:text-primary"
                to={`/projects/${encodeURIComponent(p.project_id)}`}
              >
                <ChevronRight className="size-4" />
              </Link>
            ) : (
              <span className="size-4 shrink-0" />
            )}
          </li>
        ))}
      </ul>
      {projects.data?.length === 0 && (
        <p className="text-tertiary px-6 py-10 text-center text-sm">
          No associated projects.
        </p>
      )}
      {open && (
        <LinkProjectDialog
          exclude={new Set((projects.data ?? []).map((p) => p.project_id))}
          onClose={() => setOpen(false)}
          orgSlug={orgSlug}
          shortId={task.short_id}
        />
      )}
    </div>
  )
}

/** Pick a project of the org and associate it (design: "Link project"). */
export function LinkProjectDialog({
  exclude,
  onClose,
  orgSlug,
  shortId,
}: {
  exclude: Set<string>
  onClose: () => void
  orgSlug: string
  shortId: string
}) {
  const [text, setText] = useState('')
  const [pick, setPick] = useState<null | string>(null)
  const { projectsById } = useProjectsSlimMap(orgSlug)
  const link = useAgentTaskRelationMutation(orgSlug, (projectId: string) =>
    setAgentTaskProject(orgSlug, shortId, projectId, true),
  )
  const q = text.trim().toLowerCase()
  const results = [...projectsById.values()]
    .filter((p) => !exclude.has(p.id))
    .filter(
      (p) =>
        !q || `${p.name} ${p.slug} ${p.team.name}`.toLowerCase().includes(q),
    )
    .sort((a, b) => a.name.localeCompare(b.name))
  const picked = pick ? projectsById.get(pick) : undefined
  return (
    <Dialog onOpenChange={(o) => !o && onClose()} open>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Link project</DialogTitle>
          <DialogDescription>
            Pick a project this task touches.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <Input
            aria-label="Search projects"
            onChange={(e) => setText(e.target.value)}
            placeholder="Search projects by name or team"
            value={text}
          />
          <ul
            aria-label="Projects"
            className="border-tertiary max-h-80 overflow-y-auto rounded-md border"
          >
            {results.map((p) => (
              <li
                className="border-tertiary border-b last:border-b-0"
                key={p.id}
              >
                <button
                  aria-pressed={pick === p.id}
                  className={cn(
                    'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
                    pick === p.id ? 'bg-amber-bg' : 'hover:bg-secondary',
                  )}
                  onClick={() => setPick(pick === p.id ? null : p.id)}
                  type="button"
                >
                  <Box className="text-tertiary size-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {p.name}
                  </span>
                  <span className="text-tertiary text-xs whitespace-nowrap">
                    {p.team.name}
                  </span>
                </button>
              </li>
            ))}
            {results.length === 0 && (
              <li className="text-tertiary px-4 py-8 text-center text-sm">
                No projects match that search.
              </li>
            )}
          </ul>
          {link.error && (
            <p className="text-danger text-sm" role="alert">
              {errorMessage(link.error)}
            </p>
          )}
          <div className="flex items-center justify-end gap-3">
            <span className="text-secondary text-sm">
              {picked ? `Linking ${picked.name}` : 'Choose a project to link'}
            </span>
            <Button
              disabled={!pick || link.isPending}
              onClick={() => link.mutate(pick!, { onSuccess: onClose })}
            >
              <Link2 className="mr-2 size-4" />
              Link project
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Pick a task and the relation, then link it (design: "Link task"). */
export function LinkTaskDialog({
  exclude,
  onClose,
  orgSlug,
  shortId,
}: {
  exclude: Set<string>
  onClose: () => void
  orgSlug: string
  shortId: string
}) {
  const [text, setText] = useState('')
  const q = useDebouncedValue(text.trim(), 250)
  const [pick, setPick] = useState<null | string>(null)
  const [kind, setKind] = useState<LinkKind>('requires')
  const { data: agents } = useAgentList(orgSlug)
  const found = useQuery({
    queryFn: ({ signal }) =>
      listAgentTasks(orgSlug, { limit: 20, q: q || undefined }, signal),
    queryKey: queryKeys.agentTasks(orgSlug, { link: q }),
  })
  const link = useAgentTaskRelationMutation(orgSlug, (other: string) =>
    KINDS[kind].requires
      ? setAgentTaskDependency(orgSlug, shortId, other, true)
      : setAgentTaskDependency(orgSlug, other, shortId, true),
  )
  const results = (found.data ?? []).filter((t) => !exclude.has(t.short_id))
  return (
    <Dialog onOpenChange={(o) => !o && onClose()} open>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Link task</DialogTitle>
          <DialogDescription>
            Choose the task, then set the relationship.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6">
          <Input
            aria-label="Search tasks"
            onChange={(e) => setText(e.target.value)}
            placeholder="Search tasks by id, title, project, or agent"
            value={text}
          />
          <ul
            aria-label="Tasks"
            className="border-tertiary max-h-80 overflow-y-auto rounded-md border"
          >
            {results.map((t) => (
              <li
                className="border-tertiary border-b last:border-b-0"
                key={t.id}
              >
                <button
                  aria-pressed={pick === t.short_id}
                  className={cn(
                    'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
                    pick === t.short_id ? 'bg-amber-bg' : 'hover:bg-secondary',
                  )}
                  onClick={() =>
                    setPick(pick === t.short_id ? null : t.short_id)
                  }
                  type="button"
                >
                  <span className="text-tertiary shrink-0 font-mono text-xs tabular-nums">
                    {t.short_id}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {t.title}
                  </span>
                  <span className="text-tertiary text-xs whitespace-nowrap">
                    {agents?.find((a) => a.id === t.agent_id)?.name ?? ''}
                  </span>
                  <Badge variant={statusVariant(t)}>{statusLabel(t)}</Badge>
                </button>
              </li>
            ))}
            {found.data && results.length === 0 && (
              <li className="text-tertiary px-4 py-8 text-center text-sm">
                No tasks match that search.
              </li>
            )}
          </ul>
          <div
            className={cn(
              'flex flex-col gap-2 transition-opacity',
              !pick && 'opacity-45',
            )}
          >
            <span className="text-overline text-tertiary uppercase">
              Relationship
            </span>
            <SegmentedControl
              ariaLabel="Relationship"
              className="self-start"
              onValueChange={(v) => setKind(v as LinkKind)}
              value={kind}
            >
              {LINK_KINDS.map((k) => (
                <SegmentedControlItem disabled={!pick} key={k} value={k}>
                  {KINDS[k].label}
                </SegmentedControlItem>
              ))}
            </SegmentedControl>
            <p className="text-secondary text-sm">
              {pick
                ? linkHint(shortId, pick, kind)
                : 'Choose a task above, then set the relationship.'}
            </p>
          </div>
          {link.error && (
            <p className="text-danger text-sm" role="alert">
              {errorMessage(link.error)}
            </p>
          )}
          <Button
            className="self-end"
            disabled={!pick || link.isPending}
            onClick={() => link.mutate(pick!, { onSuccess: onClose })}
          >
            <Link2 className="mr-2 size-4" />
            Link
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Requires, required by, parent, and children of the task. */
export function RelatedTasksTab({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: AgentTask
}) {
  const canManage = useHasPermission('agent_task:manage')
  const relations = useAgentTaskRelations(orgSlug, task.short_id)
  const { data: agents } = useAgentList(orgSlug)
  const [open, setOpen] = useState(false)
  const unlink = useAgentTaskRelationMutation(
    orgSlug,
    ([dependent, prerequisite]: [string, string]) =>
      setAgentTaskDependency(orgSlug, dependent, prerequisite, false),
  )
  const r = relations.data
  const rows: Row[] = r
    ? [
        ...r.requires.map((t) => ({
          alias: 'blocked by',
          kind: 'Requires',
          link: [task.short_id, t.short_id] as [string, string],
          task: t,
          tone: 'info' as const,
        })),
        ...r.required_by.map((t) => ({
          alias: 'blocks',
          kind: 'Required by',
          link: [t.short_id, task.short_id] as [string, string],
          task: t,
          tone: 'neutral' as const,
        })),
        ...(r.parent ? [r.parent] : []).map((t) => ({
          alias: 'delegation',
          kind: 'Parent',
          task: t,
          tone: 'accent' as const,
        })),
        ...r.children.map((t) => ({
          alias: 'delegation',
          kind: 'Child',
          task: t,
          tone: 'accent' as const,
        })),
      ]
    : []
  const linked = new Set([
    task.short_id,
    ...(r?.requires ?? []).map((t) => t.short_id),
    ...(r?.required_by ?? []).map((t) => t.short_id),
  ])
  return (
    <div>
      <PanelHeader
        action={
          canManage && (
            <Button onClick={() => setOpen(true)} size="sm" variant="outline">
              Link task
            </Button>
          )
        }
      >
        Tasks this one requires or is required by, and its delegation
      </PanelHeader>
      {relations.error && (
        <p className="text-danger px-6 py-3 text-sm" role="alert">
          {errorMessage(relations.error)}
        </p>
      )}
      {unlink.error && (
        <p className="text-danger px-6 py-3 text-sm" role="alert">
          {errorMessage(unlink.error)}
        </p>
      )}
      <ul aria-label="Related tasks">
        {rows.map((row) => (
          <li
            className="border-tertiary hover:bg-secondary flex items-center gap-4 border-b px-6 py-3"
            key={`${row.kind}-${row.task.short_id}`}
          >
            <span className="flex w-44 shrink-0 items-center gap-1.5">
              <Badge variant={row.tone}>{row.kind}</Badge>
              <span className="text-tertiary text-xs">{row.alias}</span>
            </span>
            <Link
              className="flex min-w-0 flex-1 items-center gap-4"
              to={agentsPath('tasks', orgSlug, row.task.short_id)}
            >
              <span className="text-tertiary shrink-0 font-mono text-xs tabular-nums">
                {row.task.short_id}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">
                {row.task.title}
              </span>
              <span className="text-tertiary text-xs whitespace-nowrap">
                {agents?.find((a) => a.id === row.task.agent_id)?.name ?? ''}
              </span>
              <Badge variant={statusVariant(row.task)}>
                {statusLabel(row.task)}
              </Badge>
              <RelativeTime
                className="text-tertiary w-20 text-right font-mono text-xs whitespace-nowrap"
                tooltip={false}
                value={row.task.created_at}
              />
            </Link>
            {canManage && row.link ? (
              <button
                aria-label={`Remove ${row.kind.toLowerCase()} ${row.task.short_id}`}
                className="text-tertiary hover:text-danger flex size-8 shrink-0 items-center justify-center rounded-md transition-colors"
                disabled={unlink.isPending}
                onClick={() => unlink.mutate(row.link!)}
                title="Remove link"
                type="button"
              >
                <Trash2 className="size-3.5" />
              </button>
            ) : (
              canManage && <span className="size-8 shrink-0" />
            )}
          </li>
        ))}
      </ul>
      {r && rows.length === 0 && (
        <p className="text-tertiary px-6 py-10 text-center text-sm">
          No related tasks.
        </p>
      )}
      {open && (
        <LinkTaskDialog
          exclude={linked}
          onClose={() => setOpen(false)}
          orgSlug={orgSlug}
          shortId={task.short_id}
        />
      )}
    </div>
  )
}

/** "T-1 requires T-5 · T-5 blocks T-1", for the chosen kind. */
function linkHint(shortId: string, other: string, kind: LinkKind): string {
  const [dependent, prerequisite] = KINDS[kind].requires
    ? [shortId, other]
    : [other, shortId]
  return `${dependent} requires ${prerequisite} · ${prerequisite} blocks ${dependent}`
}

function PanelHeader({
  action,
  children,
}: {
  action: ReactNode
  children: ReactNode
}) {
  return (
    <div className="border-tertiary flex items-center gap-3 border-b px-6 py-3">
      <span className="text-tertiary text-xs">{children}</span>
      <span className="ml-auto">{action}</span>
    </div>
  )
}
