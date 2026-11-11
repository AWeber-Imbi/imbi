import { useState } from 'react'

import { Activity, Check, Hand } from 'lucide-react'

import { ApiError } from '@/api/client'
import { replyAgentTask, resolveAgentTaskRequest } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Textarea } from '@/components/ui/textarea'
import { useHasPermission } from '@/hooks/useHasPermission'
import type { AgentTask, AgentTaskEvent, AgentTaskResolve } from '@/types'

import { checksFrom, type TaskRequestView } from './taskEvents'
import { errorMessage, useAgentTaskMutation } from './taskQueries'
import { RESOLVED, useActorName } from './taskText'

/** The badge of the check verdicts the design knows; others show as is. */
const VERDICT: Record<
  string,
  undefined | { label: string; variant: 'danger' | 'success' | 'warning' }
> = {
  fail: { label: 'Failing', variant: 'danger' },
  pass: { label: 'Passing', variant: 'success' },
  warn: { label: 'Watch', variant: 'warning' },
}

/**
 * The latest report of each check: value, delta, baseline, verdict, and
 * source (J2).
 */
export function ChecksTab({ events }: { events: AgentTaskEvent[] }) {
  const checks = checksFrom(events)
  if (checks.length === 0) {
    return <p className="p-6 text-sm text-tertiary">No checks reported yet.</p>
  }
  return (
    <div>
      <p className="border-b border-tertiary px-6 py-3 text-xs text-tertiary">
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
              className="flex items-center gap-3 border-b border-tertiary px-6 py-3"
              key={e.event_id}
            >
              <Activity className="size-4 shrink-0 text-tertiary" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{label(p.name)}</span>
                  <Badge variant={verdict?.variant ?? 'neutral'}>
                    {verdict?.label ?? label(p.verdict ?? 'No verdict')}
                  </Badge>
                </div>
                {detail.length > 0 && (
                  <div className="text-xs text-tertiary">
                    {detail.join(' · ')}
                  </div>
                )}
              </div>
              <span className="ml-auto font-mono text-xs whitespace-nowrap text-secondary tabular-nums">
                {p.value == null ? '—' : label(p.value)}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Reply and Reply and hold: steer the task while it is open. */
export function Composer({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: AgentTask
}) {
  const canManage = useHasPermission('agent_task:manage', orgSlug)
  const [body, setBody] = useState('')
  const reply = useAgentTaskMutation(orgSlug, task.short_id, (hold: boolean) =>
    replyAgentTask(orgSlug, task.short_id, body.trim(), hold),
  )
  if (!canManage) return null
  const send = (hold: boolean) =>
    reply.mutate(hold, { onSuccess: () => setBody('') })
  return (
    <div className="flex shrink-0 flex-col gap-2 border-t border-tertiary bg-primary px-6 py-3">
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
          <span className="text-xs text-danger" role="alert">
            {errorMessage(reply.error)}
          </span>
        )}
      </div>
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
      <p className="p-6 text-sm text-tertiary">
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

export function RequestCard({
  orgSlug,
  request: r,
  task,
}: {
  orgSlug: string
  request: TaskRequestView
  task: AgentTask
}) {
  const canResolve = useHasPermission('agent_task:resolve', orgSlug)
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
      <div className="flex flex-col gap-1 rounded-lg border border-tertiary px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          <Check className="size-4 shrink-0 text-success" />
          <span className="font-medium">{r.title}</span>
          <span className="ml-auto text-xs text-secondary">
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
          <p className="pl-6 text-sm whitespace-pre-wrap text-secondary">
            {r.answer}
          </p>
        )}
      </div>
    )
  }

  const actionable = canResolve && task.status !== 'closed'
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-amber-border bg-amber-bg p-4">
      <div className="flex items-center gap-2 text-xs">
        <Hand className="size-3.5 text-amber-text" />
        <span className="text-overline text-amber-text uppercase">
          Waiting on you
        </span>
        <span className="ml-auto text-amber-text">
          asked <RelativeTime tooltip={false} value={r.opened_at} /> by{' '}
          {actorName(r.opened_by)}
        </span>
      </div>
      <div>
        <h3 className="text-sm font-medium">{r.title}</h3>
        {r.why && (
          <p className="mt-1 text-sm whitespace-pre-wrap text-secondary">
            {r.why}
          </p>
        )}
      </div>
      {r.artifacts.map((a, i) => (
        <div
          className="truncate rounded border border-tertiary bg-primary px-3 py-2 font-mono text-xs"
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
        <p className="text-xs text-danger" role="alert">
          {errorMessage(resolve.error)}
        </p>
      )}
    </div>
  )
}

/** A string option or artifact as text; anything else as JSON. */
function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
