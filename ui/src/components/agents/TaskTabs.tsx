import { useState } from 'react'

import {
  Activity,
  Check,
  ChevronDown,
  ChevronUp,
  CornerDownRight,
  Hand,
  Wrench,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import { replyAgentTask, resolveAgentTaskRequest } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Textarea } from '@/components/ui/textarea'
import { UserIdentity } from '@/components/ui/user-identity'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent, AgentTaskResolve } from '@/types'

import { useAgentList } from './agentQueries'
import {
  checksFrom,
  conversation,
  formatElapsed,
  statusLabel,
  type TaskRequestView,
  toolCalls,
} from './taskEvents'
import { errorMessage, useAgentTaskMutation } from './taskQueries'

const ROLE: Record<AgentTaskEvent['actor_kind'], string> = {
  agent: 'Agent',
  human: 'Person',
  subagent: 'Subagent',
  system: 'System',
}

/** The badge of the check verdicts the design knows; others show as is. */
const VERDICT: Record<
  string,
  undefined | { label: string; variant: 'danger' | 'success' | 'warning' }
> = {
  fail: { label: 'Failing', variant: 'danger' },
  pass: { label: 'Passing', variant: 'success' },
  warn: { label: 'Watch', variant: 'warning' },
}

const RESOLVED: Record<TaskRequestView['status'], string> = {
  answered: 'Answered',
  approved: 'Approved',
  expired: 'Expired',
  open: 'Open',
  rejected: 'Rejected',
}

/** Tool calls in seq order, nested calls under their parent (N3). */
export function ActionsTab({
  events,
  orgSlug,
}: {
  events: AgentTaskEvent[]
  orgSlug: string
}) {
  const [open, setOpen] = useState(new Set<number>())
  const actorName = useActorName(orgSlug)
  const rows = toolCalls(events)
  if (rows.length === 0) {
    return <p className="text-tertiary p-6 text-sm">No tool calls yet.</p>
  }
  return (
    <ul>
      {rows.map(({ depth, event }) => {
        const p = event.payload
        const expanded = open.has(event.seq)
        const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
        return (
          <li className="border-tertiary border-b" key={event.event_id}>
            <button
              aria-expanded={expanded}
              className="hover:bg-secondary flex w-full items-center gap-3 py-2.5 pr-6 text-left text-sm"
              onClick={() => {
                const next = new Set(open)
                if (!next.delete(event.seq)) next.add(event.seq)
                setOpen(next)
              }}
              style={{ paddingLeft: 24 + depth * 24 }}
              type="button"
            >
              {depth > 0 ? (
                <CornerDownRight className="text-tertiary size-3.5 shrink-0" />
              ) : (
                <Wrench className="text-tertiary size-3.5 shrink-0" />
              )}
              <span className="text-tertiary font-mono text-xs tabular-nums">
                {clock(event.at)}
              </span>
              <span className="truncate font-medium">
                {String(p.tool ?? 'tool')}
              </span>
              <span className="text-tertiary truncate text-xs">
                {actorName(event.actor_id)}
              </span>
              {p.mutating === true && <Badge variant="warning">mutating</Badge>}
              <span className="text-secondary ml-auto font-mono text-xs tabular-nums">
                {ms == null ? '—' : ms < 1000 ? `${ms}ms` : formatElapsed(ms)}
              </span>
              {expanded ? (
                <ChevronUp className="text-tertiary size-4" />
              ) : (
                <ChevronDown className="text-tertiary size-4" />
              )}
            </button>
            {expanded && (
              <div
                className="bg-secondary flex flex-col gap-2 py-3 pr-6 text-sm"
                style={{ paddingLeft: 48 + depth * 24 }}
              >
                {p.result_summary != null && (
                  <p className="text-secondary">{String(p.result_summary)}</p>
                )}
                {(['arguments', 'result'] as const).map(
                  (key) =>
                    p[key] != null && (
                      <div key={key}>
                        <div className="text-overline text-tertiary uppercase">
                          {key}
                        </div>
                        <pre className="font-mono text-xs whitespace-pre-wrap">
                          {JSON.stringify(p[key], null, 2)}
                        </pre>
                      </div>
                    ),
                )}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The latest report of each check: value, delta, baseline, verdict, and
 * source (J2).
 */
export function ChecksTab({ events }: { events: AgentTaskEvent[] }) {
  const checks = checksFrom(events)
  if (checks.length === 0) {
    return <p className="text-tertiary p-6 text-sm">No checks reported yet.</p>
  }
  return (
    <div>
      <p className="border-tertiary text-tertiary border-b px-6 py-3 text-xs">
        Signals the agent and its subagents report against this task
      </p>
      <ul>
        {checks.map((e) => {
          // Only the payload fields that ADR 0020 names. Who ran the
          // check (its provenance) comes later, from the harness plan.
          const p = e.payload
          const verdict = VERDICT[String(p.verdict)]
          const delta =
            typeof p.delta === 'number' && p.delta > 0 ? `+${p.delta}` : p.delta
          const detail = [
            delta != null && `delta ${label(delta)}`,
            p.baseline != null && `baseline ${label(p.baseline)}`,
            p.source != null && `source ${label(p.source)}`,
          ].filter(Boolean)
          return (
            <li
              className="border-tertiary flex items-center gap-3 border-b px-6 py-3"
              key={e.event_id}
            >
              <Activity className="text-tertiary size-4 shrink-0" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{label(p.name)}</span>
                  <Badge variant={verdict?.variant ?? 'neutral'}>
                    {verdict?.label ?? label(p.verdict ?? 'No verdict')}
                  </Badge>
                </div>
                {detail.length > 0 && (
                  <div className="text-tertiary text-xs">
                    {detail.join(' · ')}
                  </div>
                )}
              </div>
              <span className="text-secondary ml-auto font-mono text-xs whitespace-nowrap tabular-nums">
                {p.value == null ? '—' : label(p.value)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * Turns labelled by role, with state changes inline as system entries
 * (O5), and the Reply and Reply and hold composer.
 */
export function ConversationTab({
  events,
  orgSlug,
  task,
}: {
  events: AgentTaskEvent[]
  orgSlug: string
  task: AgentTask
}) {
  const actorName = useActorName(orgSlug)
  const entries = conversation(events)
  return (
    <div className="flex min-h-full flex-col">
      <ul className="flex-1">
        {entries.length === 0 && (
          <li className="text-tertiary p-6 text-sm">No conversation yet.</li>
        )}
        {entries.map((e) =>
          e.type === 'turn' ? (
            <li
              className={cn(
                'border-tertiary flex flex-col gap-1.5 border-b px-6 py-3',
                e.actor_kind === 'human' && 'bg-secondary',
              )}
              key={e.event_id}
            >
              <div className="flex items-center gap-2">
                {e.actor_kind === 'human' ? (
                  <UserIdentity email={e.actor_id} size="small" />
                ) : (
                  <span className="text-sm font-medium">
                    {actorName(e.actor_id)}
                  </span>
                )}
                <Badge variant={e.actor_kind === 'human' ? 'info' : 'neutral'}>
                  {ROLE[e.actor_kind]}
                </Badge>
                {!['harness', 'web'].includes(e.channel) && (
                  <span className="text-tertiary text-xs">via {e.channel}</span>
                )}
                <span className="text-tertiary ml-auto font-mono text-xs">
                  {clock(e.at)}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap">
                {String(e.payload.body ?? '')}
              </p>
              {typeof e.payload.decision === 'string' && (
                <p className="border-tertiary text-secondary flex items-center gap-2 rounded border px-3 py-1.5 text-sm">
                  <Hand className="size-3.5" />
                  {e.payload.decision}
                </p>
              )}
            </li>
          ) : (
            <li
              className="border-tertiary text-tertiary flex items-center gap-2 border-b px-6 py-1.5 text-xs"
              key={e.event_id}
            >
              <span className="flex-1">{systemText(e)}</span>
              <span className="font-mono">{clock(e.at)}</span>
            </li>
          ),
        )}
      </ul>
      {task.status !== 'closed' && <Composer orgSlug={orgSlug} task={task} />}
    </div>
  )
}

/** Requests that wait on a person, and who resolved the others (I4). */
export function InputRequiredTab({
  orgSlug,
  requests,
  task,
}: {
  orgSlug: string
  requests: TaskRequestView[]
  task: AgentTask
}) {
  if (requests.length === 0) {
    return (
      <p className="text-tertiary p-6 text-sm">
        This task has not asked for input.
      </p>
    )
  }
  const ordered = [
    ...requests.filter((r) => r.status === 'open'),
    ...requests.filter((r) => r.status !== 'open').reverse(),
  ]
  return (
    <div className="flex flex-col gap-3 px-6 py-5">
      {ordered.map((r) => (
        <RequestCard key={r.id} orgSlug={orgSlug} request={r} task={task} />
      ))}
    </div>
  )
}

function clock(at: string): string {
  return new Date(at).toLocaleTimeString([], { hour12: false })
}

function Composer({ orgSlug, task }: { orgSlug: string; task: AgentTask }) {
  const canManage = useHasPermission('agent_task:manage')
  const [body, setBody] = useState('')
  const reply = useAgentTaskMutation(orgSlug, task.short_id, (hold: boolean) =>
    replyAgentTask(orgSlug, task.short_id, body.trim(), hold),
  )
  if (!canManage) return null
  const send = (hold: boolean) =>
    reply.mutate(hold, { onSuccess: () => setBody('') })
  return (
    <div className="border-tertiary bg-primary sticky bottom-0 flex flex-col gap-2 border-t px-6 py-3">
      <Textarea
        aria-label="Reply"
        onChange={(e) => setBody(e.target.value)}
        placeholder="Add a comment, answer a question, or steer the agent"
        rows={3}
        value={body}
      />
      <div className="flex items-center gap-2">
        <Button
          disabled={!body.trim() || reply.isPending}
          onClick={() => send(false)}
          size="sm"
        >
          Reply
        </Button>
        <Button
          disabled={!body.trim() || reply.isPending}
          onClick={() => send(true)}
          size="sm"
          title="Reply and pause the task"
          variant="outline"
        >
          Reply and hold
        </Button>
        {reply.error && (
          <span className="text-danger text-xs" role="alert">
            {errorMessage(reply.error)}
          </span>
        )}
      </div>
    </div>
  )
}

/** A string option or artifact as text; anything else as JSON. */
function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function RequestCard({
  orgSlug,
  request: r,
  task,
}: {
  orgSlug: string
  request: TaskRequestView
  task: AgentTask
}) {
  const canResolve = useHasPermission('agent_task:resolve')
  const actorName = useActorName(orgSlug)
  const [answer, setAnswer] = useState('')
  // Someone else resolved it first: collapse in place (I4).
  const [taken, setTaken] = useState<null | { by: string; status: string }>(
    null,
  )
  const resolve = useAgentTaskMutation(
    orgSlug,
    task.short_id,
    (resolution: AgentTaskResolve) =>
      resolveAgentTaskRequest(orgSlug, task.short_id, r.id, resolution),
  )
  const submit = (resolution: AgentTaskResolve) =>
    resolve.mutate(resolution, {
      onError: (error) => {
        const detail =
          error instanceof ApiError
            ? (error.data as undefined | { detail?: Record<string, string> })
                ?.detail
            : undefined
        if (error instanceof ApiError && detail?.error === 'request_resolved')
          setTaken({ by: detail.resolved_by, status: detail.status })
      },
    })

  if (r.status !== 'open' || taken) {
    const status = taken
      ? (RESOLVED[taken.status as TaskRequestView['status']] ?? taken.status)
      : RESOLVED[r.status]
    const by = taken?.by ?? r.resolved_by
    return (
      <div className="border-tertiary flex flex-col gap-1 rounded-lg border px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          <Check className="text-success size-4 shrink-0" />
          <span className="font-medium">{r.title}</span>
          <span className="text-secondary ml-auto text-xs">
            {status}
            {by && ` by ${by}`}
            {r.resolved_at && !taken && (
              <>
                {' · '}
                <RelativeTime tooltip={false} value={r.resolved_at} />
              </>
            )}
          </span>
        </div>
        {r.answer && !taken && (
          <p className="text-secondary pl-6 text-sm whitespace-pre-wrap">
            {r.answer}
          </p>
        )}
      </div>
    )
  }

  const actionable = canResolve && task.status !== 'closed'
  return (
    <div className="border-amber-border bg-amber-bg flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-center gap-2 text-xs">
        <Hand className="text-amber-text size-3.5" />
        <span className="text-overline text-amber-text uppercase">
          Waiting on you
        </span>
        <span className="text-amber-text ml-auto">
          asked <RelativeTime tooltip={false} value={r.opened_at} /> by{' '}
          {actorName(r.opened_by)}
        </span>
      </div>
      <div>
        <h3 className="text-sm font-medium">{r.title}</h3>
        {r.why && (
          <p className="text-secondary mt-1 text-sm whitespace-pre-wrap">
            {r.why}
          </p>
        )}
      </div>
      {r.artifacts.map((a, i) => (
        <div
          className="border-tertiary bg-primary truncate rounded border px-3 py-2 font-mono text-xs"
          key={i}
        >
          {label(a)}
        </div>
      ))}
      {actionable && r.kind === 'approval' && (
        <div className="flex gap-2">
          <Button
            disabled={resolve.isPending}
            onClick={() =>
              submit({
                artifact_digests: r.artifact_digests ?? [],
                status: 'approved',
              })
            }
            size="sm"
          >
            Approve
          </Button>
          <Button
            disabled={resolve.isPending}
            onClick={() => submit({ status: 'rejected' })}
            size="sm"
            variant="outline"
          >
            Reject
          </Button>
        </div>
      )}
      {actionable && r.kind === 'feedback' && (
        <div className="flex flex-col gap-2">
          {r.options.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {r.options.map((o, i) => (
                <Button
                  disabled={resolve.isPending}
                  key={i}
                  onClick={() =>
                    submit({ answer: label(o), status: 'answered' })
                  }
                  size="sm"
                  variant="outline"
                >
                  {label(o)}
                </Button>
              ))}
            </div>
          )}
          <Textarea
            aria-label="Answer"
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Answer in your own words"
            rows={2}
            value={answer}
          />
          <div>
            <Button
              disabled={!answer.trim() || resolve.isPending}
              onClick={() =>
                submit({ answer: answer.trim(), status: 'answered' })
              }
              size="sm"
            >
              Send answer
            </Button>
          </div>
        </div>
      )}
      {resolve.error && (
        <p className="text-danger text-xs" role="alert">
          {errorMessage(resolve.error)}
        </p>
      )}
    </div>
  )
}

/** One line for an event that is not a turn. */
function systemText(e: AgentTaskEvent): string {
  const p = e.payload
  switch (e.type) {
    case 'control.changed':
      return `Control ${p.from} → ${p.to} by ${e.actor_id ?? 'system'}`
    case 'outcome.set':
      return `Closed: ${statusLabel({ outcome: String(p.outcome), status: 'closed' })}${p.reason ? ` (${p.reason})` : ''}`
    case 'owner.changed':
      return `Owner ${p.from} → ${p.to}`
    case 'request.opened':
      return `Asked for ${p.kind === 'approval' ? 'approval' : 'input'}: ${p.title}`
    case 'request.resolved':
      return `${RESOLVED[p.status as TaskRequestView['status']] ?? p.status} by ${p.resolved_by ?? e.actor_id}`
    case 'state.changed':
      return `Status ${p.from} → ${p.to}${p.reason ? ` (${p.reason})` : ''}`
    default:
      return e.type
  }
}

/** The agent name for an agent actor id; other ids as they are. */
function useActorName(orgSlug: string) {
  const { data: agents } = useAgentList(orgSlug)
  return (id: null | string | undefined) =>
    agents?.find((a) => a.id === id)?.name ?? id ?? 'Unknown'
}
