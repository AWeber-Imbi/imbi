import { useMemo } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { History } from 'lucide-react'

import {
  listEnvironments,
  listOperationsLog,
  listProjectEvents,
} from '@/api/endpoints'
import type { EventRecord } from '@/api/endpoints'
import { renderEntryLabel } from '@/components/operations-log/renderEntryLabel'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { Sk } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { UserIdentity } from '@/components/ui/user-identity'
import { usePluginOpsLogTemplates } from '@/hooks/usePluginOpsLogTemplates'
import type { PluginOpsLogTemplateMap } from '@/hooks/usePluginOpsLogTemplates'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { formatFieldKey } from '@/lib/project-field-formatting'
import type { Environment, OperationsLogRecord } from '@/types'

const MAX_ROWS = 20

type ActivityItem =
  | { data: EventRecord; kind: 'event'; ts: Date }
  | { data: OperationsLogRecord; kind: 'ops'; ts: Date }

type AvatarColor = keyof typeof DOT_CLASS

interface DocumentCommentPayload extends Record<string, unknown> {
  action?: string
  document_id?: string
  excerpt?: string
  kind?: string
  thread_id?: string
}

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
  info: 'bg-activity-info-dot',
  neutral: 'bg-activity-neutral-dot',
  warning: 'bg-activity-warning-dot',
}

interface KeyChange {
  key: string
  kind: 'added' | 'changed' | 'removed'
  newValue?: string
  oldValue?: string
}

export function ProjectActivityLog({ orgSlug, projectId, projectSlug }: Props) {
  const { templates } = usePluginOpsLogTemplates()
  const { data: eventsPage, isPending: eventsPending } = useQuery({
    enabled: Boolean(orgSlug) && Boolean(projectId),
    queryFn: ({ signal }) =>
      listProjectEvents({ limit: MAX_ROWS, orgSlug, projectId }, signal),
    queryKey: ['events', orgSlug, projectId],
    // 30s matches the opsLog query above. Activity events are roughly
    // append-only from the user's perspective; refetch-on-focus still
    // picks up genuinely new activity within a focus cycle.
    staleTime: 30_000,
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

  const { displayNames } = useUserDisplayNames()

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
        <ActivityLogSkeleton />
      ) : merged.length === 0 ? (
        <div className="text-tertiary flex flex-col items-center justify-center gap-2 py-10">
          <History className="size-5" />
          <span className="text-sm">No activity recorded yet.</span>
        </div>
      ) : (
        <div>
          {groups.map((group) => (
            <div key={group.label}>
              <div className="text-tertiary px-6 pt-2 pb-1 text-[11px] font-semibold tracking-widest uppercase">
                {group.label}
              </div>

              <div className="relative px-6">
                <div className="bg-muted absolute top-4 bottom-4 left-[31.5px] w-px" />

                {group.items.map((item, i) =>
                  item.kind === 'event' ? (
                    <EventEntry
                      displayNames={displayNames}
                      item={item}
                      key={`event-${item.data.id}-${i}`}
                      projectId={projectId}
                    />
                  ) : (
                    <OpsEntry
                      displayNames={displayNames}
                      envMap={envMap}
                      item={item}
                      key={`ops-${item.data.id}-${i}`}
                      templates={templates}
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

function ActivityLogSkeleton() {
  return (
    <div className="px-6 pt-2">
      <Sk className="mb-2" h={11} w={48} />
      <div className="relative">
        <div className="bg-muted absolute top-4 bottom-4 left-[7.5px] w-px" />
        {[0, 1, 2, 3].map((i) => (
          <div className="relative flex gap-3 py-3" key={i}>
            <div className="relative flex w-4 shrink-0 flex-col items-center">
              <Sk circle className="mt-1.5" h={8} w={8} />
            </div>
            <Sk circle h={32} w={32} />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <Sk h={14} w="30%" />
                <Sk h={11} w={56} />
              </div>
              <Sk h={12} w="70%" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Deep-link to a comment's document, focusing the thread via ?thread=. */
// fallow-ignore-next-line complexity
function commentHref(projectId: string, payload: unknown): string | undefined {
  const p: DocumentCommentPayload = isPlainObject(payload) ? payload : {}
  const documentId = typeof p.document_id === 'string' ? p.document_id : ''
  if (!documentId) return undefined
  const base = `/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`
  return typeof p.thread_id === 'string' && p.thread_id
    ? `${base}?thread=${encodeURIComponent(p.thread_id)}`
    : base
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

// fallow-ignore-next-line complexity
function diffObjects(
  oldObj: Record<string, unknown>,
  newObj: Record<string, unknown>,
): KeyChange[] {
  const keys = new Set([...Object.keys(oldObj), ...Object.keys(newObj)])
  const changes: KeyChange[] = []
  for (const key of keys) {
    const hasOld = key in oldObj
    const hasNew = key in newObj
    if (!hasOld && hasNew) {
      changes.push({ key, kind: 'added', newValue: formatValue(newObj[key]) })
    } else if (hasOld && !hasNew) {
      changes.push({ key, kind: 'removed', oldValue: formatValue(oldObj[key]) })
    } else if (formatValue(oldObj[key]) !== formatValue(newObj[key])) {
      changes.push({
        key,
        kind: 'changed',
        newValue: formatValue(newObj[key]),
        oldValue: formatValue(oldObj[key]),
      })
    }
  }
  return changes.sort((a, b) => a.key.localeCompare(b.key))
}

function EntryRow({
  actor,
  avatarColor,
  body,
  href,
  name,
  ts,
}: {
  actor: string
  avatarColor: AvatarColor
  body: React.ReactNode
  href?: string
  name: string
  ts: Date
}) {
  // Only a real email drives Gravatar/profile resolution; a bare actor login
  // is routed via the actor prop so bot detection works and we skip a doomed
  // Gravatar lookup.
  const email = actor.includes('@') ? actor : undefined
  return (
    <div
      className={`relative flex gap-3 py-3 ${href ? 'hover:bg-secondary/40 -mx-2 rounded-md px-2' : ''}`}
    >
      <div className="relative flex w-4 shrink-0 flex-col items-center">
        <div
          className={`ring-primary relative z-10 mt-1.5 size-2 shrink-0 rounded-full ring-2 ${DOT_CLASS[avatarColor]}`}
        />
      </div>
      <UserIdentity
        actor={actor}
        displayName={name}
        email={email}
        hideName
        linkToProfile={false}
        size="floating"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-primary truncate font-semibold">{name}</span>
          <Timestamp ts={ts} />
        </div>
        <div className="text-secondary mt-0.5 text-sm">{body}</div>
      </div>
      {href && (
        <Link
          aria-label="Open comment"
          className="absolute inset-0"
          to={href}
        />
      )}
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
  projectId,
}: {
  displayNames: Map<string, string>
  item: ActivityItem & { kind: 'event' }
  projectId: string
}) {
  const entry = item.data
  const name = getDisplayName(entry.attributed_to, displayNames)

  let body: React.ReactNode
  let href: string | undefined
  if (
    entry.type === 'project-change' &&
    isProjectChangePayload(entry.payload)
  ) {
    body = renderProjectChangeBody(entry.payload)
  } else if (entry.type === 'document-comment') {
    body = renderDocumentCommentBody(entry.payload)
    href = commentHref(projectId, entry.payload)
  } else {
    body = renderGenericEventBody(entry)
  }

  return (
    <EntryRow
      actor={entry.attributed_to}
      avatarColor="info"
      body={body}
      href={href}
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

function humanizeEventType(type: string): string {
  return type.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  )
}

function isProjectChangePayload(
  payload: Record<string, unknown>,
): payload is ProjectChangePayload {
  return typeof payload.field === 'string'
}

// fallow-ignore-next-line complexity
function KeyChangeItem({ change }: { change: KeyChange }) {
  return (
    <li className="text-secondary text-xs">
      <span className="text-tertiary">{change.kind}</span>{' '}
      <ValueChip>{change.key}</ValueChip>
      {change.kind === 'changed' && (
        <>
          {': '}
          <ValueChip>{change.oldValue}</ValueChip>
          {' → '}
          <ValueChip>{change.newValue}</ValueChip>
        </>
      )}
      {change.kind === 'added' && change.newValue !== '' && (
        <>
          {': '}
          <ValueChip>{change.newValue}</ValueChip>
        </>
      )}
      {change.kind === 'removed' && change.oldValue !== '' && (
        <>
          {': '}
          <ValueChip>{change.oldValue}</ValueChip>
        </>
      )}
    </li>
  )
}

// fallow-ignore-next-line complexity
function OpsEntry({
  displayNames,
  envMap,
  item,
  templates,
}: {
  displayNames: Map<string, string>
  envMap: Map<string, Environment>
  item: ActivityItem & { kind: 'ops' }
  templates: PluginOpsLogTemplateMap
}) {
  const op = item.data
  const actor = op.performed_by ?? op.recorded_by
  const name = getDisplayName(actor, displayNames)
  const color: AvatarColor =
    op.entry_type === 'Deployed' ? 'warning' : 'neutral'
  const env = envMap.get(op.environment_slug)
  const label = renderEntryLabel(op, {
    environment: env,
    performerDisplayName: name,
    templates,
  })

  const body = (
    <span>
      {label || op.entry_type.toLowerCase()}
      {env && (
        <>
          {' on '}
          <EnvChip env={env} />
        </>
      )}
    </span>
  )

  return (
    <EntryRow
      actor={actor}
      avatarColor={color}
      body={body}
      name={name}
      ts={item.ts}
    />
  )
}

// fallow-ignore-next-line complexity
function renderDocumentCommentBody(payload: unknown): React.ReactNode {
  const p: DocumentCommentPayload = isPlainObject(payload) ? payload : {}
  const action =
    p.action === 'replied'
      ? 'replied to a comment'
      : p.kind === 'inline'
        ? 'added an inline comment'
        : 'commented on a document'
  const excerpt = typeof p.excerpt === 'string' ? p.excerpt.trim() : ''
  return (
    <span>
      <span className="text-secondary">{action}</span>
      {excerpt && <span className="text-tertiary"> — “{excerpt}”</span>}
    </span>
  )
}

function renderGenericEventBody(entry: EventRecord): React.ReactNode {
  const label = humanizeEventType(entry.type)
  return (
    <span>
      <span className="text-secondary">{label}</span>
      {entry.third_party_service && (
        <span className="text-tertiary"> via {entry.third_party_service}</span>
      )}
    </span>
  )
}

// fallow-ignore-next-line complexity
function renderProjectChangeBody(
  payload: ProjectChangePayload,
): React.ReactNode {
  const field = formatFieldKey(payload.field)
  const oldIsObj = isPlainObject(payload.old)
  const newIsObj = isPlainObject(payload.new)
  if (oldIsObj || newIsObj) {
    const changes = diffObjects(
      oldIsObj ? (payload.old as Record<string, unknown>) : {},
      newIsObj ? (payload.new as Record<string, unknown>) : {},
    )
    if (changes.length > 0) {
      return (
        <span>
          changed {field}
          <ul className="mt-1 space-y-0.5">
            {changes.map((c) => (
              <KeyChangeItem change={c} key={c.key} />
            ))}
          </ul>
        </span>
      )
    }
  }
  const oldStr = formatValue(payload.old)
  const newStr = formatValue(payload.new)
  return (
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
}

function Timestamp({ ts }: { ts: Date }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-tertiary shrink-0 cursor-default font-mono text-xs whitespace-nowrap">
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
    <code className="bg-secondary text-primary inline rounded px-1.5 py-0.5 font-mono text-xs break-all">
      {children}
    </code>
  )
}
