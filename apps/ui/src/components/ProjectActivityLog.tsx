import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { History, LoaderCircle } from 'lucide-react'

import {
  listAdminUsers,
  listEnvironments,
  listOperationsLog,
  listProjectEvents,
} from '@/api/endpoints'
import type { EventRecord } from '@/api/endpoints'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { Gravatar } from '@/components/ui/gravatar'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { formatFieldKey } from '@/lib/project-field-formatting'
import type { Environment, OperationsLogRecord } from '@/types'

const MAX_ROWS = 20

type ActivityItem =
  | { data: EventRecord; kind: 'event'; ts: Date }
  | { data: OperationsLogRecord; kind: 'ops'; ts: Date }

type AvatarColor = keyof typeof DOT_CLASS

interface ProjectChangePayload extends Record<string, unknown> {
  field: string
  new: unknown
  old: unknown
}

interface Props {
  orgSlug: string
  projectId: string
  projectSlug: string
}

const DOT_CLASS = {
  info: 'bg-[#3d86d1]',
  neutral: 'bg-[#888780]',
  warning: 'bg-[#ef9f27]',
}

export function ProjectActivityLog({ orgSlug, projectId, projectSlug }: Props) {
  const { data: eventsPage, isPending: eventsPending } = useQuery({
    enabled: Boolean(orgSlug) && Boolean(projectId),
    queryFn: ({ signal }) =>
      listProjectEvents({ limit: MAX_ROWS, orgSlug, projectId }, signal),
    queryKey: ['events', orgSlug, projectId],
    staleTime: 0,
  })

  const { data: opsPage, isPending: opsPending } = useQuery({
    enabled: Boolean(projectSlug),
    queryFn: ({ signal }) =>
      listOperationsLog(
        { filters: { project_slug: projectSlug }, limit: MAX_ROWS },
        signal,
      ),
    queryKey: ['opsLog', projectSlug],
    staleTime: 30_000,
  })

  const { data: adminUsers = [] } = useQuery({
    enabled: Boolean(orgSlug),
    queryFn: ({ signal }) => listAdminUsers({ is_active: true }, signal),
    queryKey: ['admin-users', 'active'],
    staleTime: 5 * 60_000,
  })

  const { data: environments = [] } = useQuery({
    enabled: Boolean(orgSlug),
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
    staleTime: 10 * 60_000,
  })

  const envMap = useMemo(() => {
    const m = new Map<string, Environment>()
    for (const e of environments) m.set(e.slug, e)
    return m
  }, [environments])

  const displayNames = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of adminUsers) {
      if (u.email && u.display_name) m.set(u.email, u.display_name)
    }
    return m
  }, [adminUsers])

  const isPending = eventsPending || opsPending

  const merged: ActivityItem[] = useMemo(() => {
    const events: ActivityItem[] = (eventsPage?.entries ?? []).map((e) => ({
      data: e,
      kind: 'event' as const,
      ts: new Date(e.recorded_at),
    }))
    const ops: ActivityItem[] = (opsPage?.entries ?? []).map((o) => ({
      data: o,
      kind: 'ops' as const,
      ts: new Date(o.occurred_at),
    }))
    return [...events, ...ops]
      .sort((a, b) => b.ts.getTime() - a.ts.getTime())
      .slice(0, MAX_ROWS)
  }, [eventsPage, opsPage])

  const groups = useMemo(() => {
    const map = new Map<string, { items: ActivityItem[]; label: string }>()
    for (const item of merged) {
      const key = dayKey(item.ts)
      if (!map.has(key)) map.set(key, { items: [], label: dayLabel(item.ts) })
      map.get(key)!.items.push(item)
    }
    return Array.from(map.values())
  }, [merged])

  return (
    <div>
      {isPending ? (
        <div className="flex items-center justify-center py-10 text-tertiary">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          <span className="text-sm">Loading activity…</span>
        </div>
      ) : merged.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-10 text-tertiary">
          <History className="h-5 w-5" />
          <span className="text-sm">No activity recorded yet.</span>
        </div>
      ) : (
        <div>
          {groups.map((group) => (
            <div key={group.label}>
              <div className="px-6 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-widest text-tertiary">
                {group.label}
              </div>

              <div className="relative px-6">
                <div className="absolute bottom-4 left-[26px] top-4 w-px bg-tertiary" />

                {group.items.map((item, i) =>
                  item.kind === 'event' ? (
                    <EventEntry
                      displayNames={displayNames}
                      item={item}
                      key={`event-${item.data.id}-${i}`}
                    />
                  ) : (
                    <OpsEntry
                      displayNames={displayNames}
                      envMap={envMap}
                      item={item}
                      key={`ops-${item.data.id}-${i}`}
                    />
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function dayKey(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function dayLabel(d: Date): string {
  const today = new Date()
  if (dayKey(d) === dayKey(today)) return 'TODAY'
  return d
    .toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
    .toUpperCase()
}

function EntryRow({
  avatarColor,
  body,
  email,
  name,
  ts,
}: {
  avatarColor: AvatarColor
  body: React.ReactNode
  email: string
  name: string
  ts: Date
}) {
  return (
    <div className="relative flex gap-3 py-3">
      <div className="relative flex w-4 shrink-0 flex-col items-center">
        <div
          className={`relative z-10 mt-1.5 h-2 w-2 shrink-0 rounded-full ring-2 ring-primary ${DOT_CLASS[avatarColor]}`}
        />
      </div>
      <Gravatar
        className="h-8 w-8 shrink-0 rounded-full"
        email={email}
        size={32}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-semibold text-primary">{name}</span>
          <Timestamp ts={ts} />
        </div>
        <div className="mt-0.5 text-sm text-secondary">{body}</div>
      </div>
    </div>
  )
}

function EnvChip({ env }: { env?: Environment }) {
  if (env) {
    return (
      <EnvironmentBadge
        label_color={env.label_color}
        name={env.name}
        slug={env.slug}
      />
    )
  }
  return null
}

function EventEntry({
  displayNames,
  item,
}: {
  displayNames: Map<string, string>
  item: ActivityItem & { kind: 'event' }
}) {
  const entry = item.data
  const name = getDisplayName(entry.attributed_to, displayNames)

  let body: React.ReactNode
  if (
    entry.type === 'project-change' &&
    isProjectChangePayload(entry.payload)
  ) {
    const field = formatFieldKey(entry.payload.field)
    const oldStr = formatValue(entry.payload.old)
    const newStr = formatValue(entry.payload.new)
    body = (
      <span>
        changed {field}
        {oldStr ? (
          <>
            {' '}
            <ValueChip>{oldStr}</ValueChip>
            {' → '}
            <ValueChip>{newStr}</ValueChip>
          </>
        ) : (
          <>
            {' to '}
            <ValueChip>{newStr}</ValueChip>
          </>
        )}
      </span>
    )
  } else {
    body = (
      <span className="text-tertiary">{entry.type.replace(/-/g, ' ')}</span>
    )
  }

  return (
    <EntryRow
      avatarColor="info"
      body={body}
      email={entry.attributed_to}
      name={name}
      ts={item.ts}
    />
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return JSON.stringify(value)
}

function getDisplayName(
  email: string,
  displayNames: Map<string, string>,
): string {
  return displayNames.get(email) ?? email.split('@')[0] ?? email
}

function isProjectChangePayload(
  payload: Record<string, unknown>,
): payload is ProjectChangePayload {
  return typeof payload.field === 'string'
}

function OpsEntry({
  displayNames,
  envMap,
  item,
}: {
  displayNames: Map<string, string>
  envMap: Map<string, Environment>
  item: ActivityItem & { kind: 'ops' }
}) {
  const op = item.data
  const actor = op.performed_by ?? op.recorded_by
  const name = getDisplayName(actor, displayNames)
  const color: AvatarColor =
    op.entry_type === 'Deployed' ? 'warning' : 'neutral'

  const body = (
    <span>
      {op.entry_type.toLowerCase()}
      {op.version && (
        <>
          {' '}
          <ValueChip>{op.version}</ValueChip>
        </>
      )}
      {' to '}
      <EnvChip env={envMap.get(op.environment_slug)} />
    </span>
  )

  return (
    <EntryRow
      avatarColor={color}
      body={body}
      email={actor}
      name={name}
      ts={item.ts}
    />
  )
}

function Timestamp({ ts }: { ts: Date }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="shrink-0 cursor-default whitespace-nowrap font-mono text-xs text-tertiary">
            {formatDistanceToNow(ts, { addSuffix: true })}
          </span>
        </TooltipTrigger>
        <TooltipContent>{ts.toLocaleString()}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function ValueChip({ children }: { children: React.ReactNode }) {
  return (
    <code className="inline-rounded rounded bg-secondary px-1.5 py-0.5 font-mono text-xs text-primary">
      {children}
    </code>
  )
}
