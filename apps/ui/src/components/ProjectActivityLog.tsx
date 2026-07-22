import { useMemo } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { History } from 'lucide-react'

import {
  listEnvironments,
  listIntegrations,
  listOperationsLog,
  listProjectEvents,
} from '@/api/endpoints'
import type { EventRecord } from '@/api/endpoints'
import { renderEntryLabel } from '@/components/operations-log/renderEntryLabel'
import { EntityIcon } from '@/components/ui/entity-icon'
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
import type { Environment, Integration, OperationsLogRecord } from '@/types'

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

  const { data: integrations = [], isPending: integrationsPending } = useQuery({
    enabled: Boolean(orgSlug),
    queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
    queryKey: ['integrations', orgSlug],
    staleTime: 10 * 60_000,
  })

  const integrationMap = useMemo(() => {
    const m = new Map<string, Integration>()
    for (const i of integrations) m.set(i.slug, i)
    return m
  }, [integrations])

  // Include integrations: the feed is one region with one footprint-matched
  // skeleton, and rows resolve their identity (name/avatar) from the
  // integration map. Gating on it too keeps unattributed rows from flashing a
  // raw slug or unknown avatar before their identity resolves.
  const isPending = eventsPending || opsPending || integrationsPending

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
                      integrationMap={integrationMap}
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

function asStr(value: unknown): string {
  return typeof value === 'string' ? value : ''
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

/** Map a webhook event_type + payload to a "{subject} · {outcome}" pair. */
// fallow-ignore-next-line complexity
function describeWebhook(
  eventType: string,
  payload: Record<string, unknown>,
): { outcome: string; subject: string } {
  const action = asStr(payload.action)
  switch (eventType) {
    case 'deployment': {
      const env = asStr(pick(payload, 'deployment', 'environment'))
      return {
        outcome: humanizeState(action),
        subject: env ? `Deployment to ${env}` : 'Deployment',
      }
    }
    case 'deployment_status': {
      const env =
        asStr(pick(payload, 'deployment_status', 'environment')) ||
        asStr(pick(payload, 'deployment', 'environment'))
      const state = asStr(pick(payload, 'deployment_status', 'state'))
      return {
        outcome: humanizeState(state || action),
        subject: env ? `Deployment to ${env}` : 'Deployment',
      }
    }
    case 'workflow_job': {
      const jobName = asStr(pick(payload, 'workflow_job', 'name'))
      return {
        outcome: humanizeState(
          asStr(pick(payload, 'workflow_job', 'conclusion')) ||
            asStr(pick(payload, 'workflow_job', 'status')) ||
            action,
        ),
        subject: jobName ? `Job ${jobName}` : 'Workflow job',
      }
    }
    case 'workflow_run': {
      const runName =
        asStr(pick(payload, 'workflow_run', 'name')) ||
        asStr(pick(payload, 'workflow', 'name'))
      return {
        outcome: humanizeState(
          asStr(pick(payload, 'workflow_run', 'conclusion')) ||
            asStr(pick(payload, 'workflow_run', 'status')) ||
            action,
        ),
        subject: runName ? `${runName} run` : 'Workflow run',
      }
    }
    default:
      return {
        outcome: humanizeState(action),
        subject: eventType ? humanizeEventType(eventType) : '',
      }
  }
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

// fallow-ignore-next-line complexity
function EntryRow({
  actor,
  avatarColor,
  avatarIcon,
  body,
  href,
  name,
  ts,
}: {
  actor: string
  avatarColor: AvatarColor
  /** When set, render this brand icon instead of the actor avatar. */
  avatarIcon?: string
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
      className={`relative flex items-start gap-3 py-3 ${href ? 'hover:bg-secondary/40 -mx-2 rounded-md px-2' : ''}`}
    >
      <div className="relative flex w-4 shrink-0 flex-col items-center">
        <div
          className={`ring-primary relative z-10 mt-1.5 size-2 shrink-0 rounded-full ring-2 ${DOT_CLASS[avatarColor]}`}
        />
      </div>
      {avatarIcon ? (
        <IntegrationAvatar icon={avatarIcon} title={name} />
      ) : (
        <UserIdentity
          actor={actor}
          displayName={name}
          email={email}
          hideName
          linkToProfile={false}
          size="floating"
        />
      )}
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

// fallow-ignore-next-line complexity
function EventEntry({
  displayNames,
  integrationMap,
  item,
  projectId,
}: {
  displayNames: Map<string, string>
  integrationMap: Map<string, Integration>
  item: ActivityItem & { kind: 'event' }
  projectId: string
}) {
  const entry = item.data
  const integration = entry.integration
    ? integrationMap.get(entry.integration)
    : undefined
  const integrationLabel =
    integration?.name || entry.integration || 'Unknown integration'

  // Attribution first (a real actor), then fall back to the integration's own
  // identity so a webhook row is never a nameless "?" bubble.
  const actor = resolveEventActor(entry)
  const hasActor = Boolean(actor)
  const { body, href } = renderEventBody(
    entry,
    projectId,
    integrationLabel,
    hasActor,
  )

  return (
    <EntryRow
      actor={actor}
      avatarColor="info"
      avatarIcon={
        hasActor
          ? undefined
          : integrationAvatarIcon(integration) || 'lucide-webhook'
      }
      body={body}
      href={href}
      name={hasActor ? getDisplayName(actor, displayNames) : integrationLabel}
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

/** Turn a GitHub-style status token ("in_progress") into prose. */
function humanizeState(state: string): string {
  return state.replace(/[-_]+/g, ' ').trim().toLowerCase()
}

function IntegrationAvatar({ icon, title }: { icon: string; title?: string }) {
  return (
    <span
      className="bg-secondary text-secondary relative inline-flex size-6 flex-none items-center justify-center overflow-hidden rounded-full"
      style={{ boxShadow: 'inset 0 0 0 1px var(--color-border)' }}
      title={title}
    >
      <EntityIcon className="size-3.5" icon={icon} />
    </span>
  )
}

/**
 * Brand icon for an event we couldn't attribute to a person/bot; falls back to
 * a generic webhook glyph when the integration has no icon configured.
 */
function integrationAvatarIcon(integration?: Integration): string | undefined {
  if (!integration) return undefined
  return integration.icon ?? 'lucide-webhook'
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

/** Safely read a nested string-ish value out of an untyped payload. */
function pick(obj: unknown, ...path: string[]): unknown {
  let cur = obj
  for (const key of path) {
    if (!isPlainObject(cur)) return undefined
    cur = cur[key]
  }
  return cur
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

/** Pick the body (and optional deep-link) for an event row by its type. */
// fallow-ignore-next-line complexity
function renderEventBody(
  entry: EventRecord,
  projectId: string,
  integrationLabel: string,
  hasActor: boolean,
): { body: React.ReactNode; href?: string } {
  if (
    entry.type === 'project-change' &&
    isProjectChangePayload(entry.payload)
  ) {
    return { body: renderProjectChangeBody(entry.payload) }
  }
  if (entry.type === 'document-comment') {
    return {
      body: renderDocumentCommentBody(entry.payload),
      href: commentHref(projectId, entry.payload),
    }
  }
  if (entry.type === 'webhook') {
    // Only append "via <integration>" when the row is attributed to an actor;
    // otherwise the integration is already the row's name and avatar.
    return {
      body: renderWebhookBody(entry, hasActor ? integrationLabel : undefined),
    }
  }
  // Match the webhook branch: only append "via <integration>" when the row is
  // attributed to an actor; otherwise the integration is already the identity.
  return {
    body: renderGenericEventBody(
      entry,
      hasActor ? integrationLabel : undefined,
    ),
  }
}

function renderGenericEventBody(
  entry: EventRecord,
  integrationLabel?: string,
): React.ReactNode {
  const label = humanizeEventType(entry.type)
  return (
    <span>
      <span className="text-secondary">{label}</span>
      {integrationLabel && (
        <span className="text-tertiary"> via {integrationLabel}</span>
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

/**
 * Rich, subject-aware summary for an integration webhook. Reads
 * `metadata.event_type` + the event-specific payload (environment, workflow
 * name, action/state/conclusion) so a row reads e.g. "Deployment to testing ·
 * in progress" instead of the useless "Webhook via ghec".
 */
// fallow-ignore-next-line complexity
function renderWebhookBody(
  entry: EventRecord,
  integrationLabel?: string,
): React.ReactNode {
  const eventType = asStr(entry.metadata?.event_type)
  const { outcome, subject } = describeWebhook(eventType, entry.payload)
  const label = subject || humanizeEventType(entry.type)
  return (
    <span>
      <span className="text-secondary">{label}</span>
      {outcome && <span className="text-tertiary"> · {outcome}</span>}
      {integrationLabel && (
        <span className="text-tertiary"> via {integrationLabel}</span>
      )}
    </span>
  )
}

/**
 * Best-effort actor for an event: the recorded attribution when present,
 * otherwise the sender/triggering login carried in the webhook payload.
 */
// fallow-ignore-next-line complexity
function resolveEventActor(entry: EventRecord): string {
  if (entry.attributed_to) return entry.attributed_to
  const p = entry.payload
  return (
    asStr(pick(p, 'workflow_run', 'triggering_actor', 'login')) ||
    asStr(pick(p, 'workflow_run', 'actor', 'login')) ||
    asStr(pick(p, 'sender', 'login')) ||
    asStr(pick(p, 'deployment', 'creator', 'login')) ||
    ''
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
