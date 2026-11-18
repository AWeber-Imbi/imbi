import { type FormEvent, type KeyboardEvent, useState } from 'react'

import {
  Activity,
  ArrowUp,
  Check,
  Clock,
  Hand,
  type LucideIcon,
  Pause,
  X,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import { replyAgentTask, resolveAgentTaskRequest } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireError,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireSubmit,
  QuestionnaireTitle,
} from '@/components/ui/questionnaire'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Textarea } from '@/components/ui/textarea'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent, AgentTaskResolve } from '@/types'

import { useAgentList } from './agentQueries'
import { checksFrom, type TaskRequestView } from './taskEvents'
import { AgentMark, PersonMark } from './TaskFilterBar'
import { errorMessage, useAgentTaskMutation } from './taskQueries'
import { RESOLVED, useActorName } from './taskText'

const OUTCOME: Partial<
  Record<TaskRequestView['status'], { icon: LucideIcon; tone: string }>
> = {
  answered: { icon: Check, tone: 'text-success' },
  approved: { icon: Check, tone: 'text-success' },
  expired: { icon: Clock, tone: 'text-tertiary' },
  rejected: { icon: X, tone: 'text-danger' },
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
  const ready = body.trim() !== '' && !reply.isPending
  const send = (hold: boolean) => {
    if (ready) reply.mutate(hold, { onSuccess: () => setBody('') })
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      window.matchMedia?.('(pointer: coarse)').matches
    )
      return
    event.preventDefault()
    send(false)
  }
  return (
    <div className="px-6 pt-2 pb-4">
      <form
        className="border-secondary bg-secondary focus-within:border-input pointer-events-auto mx-auto flex w-full max-w-3xl flex-col rounded-[20px] border shadow-lg transition-colors"
        onSubmit={(event) => {
          event.preventDefault()
          send(false)
        }}
      >
        <Textarea
          aria-label="Reply"
          autoResize
          className="max-h-50 min-h-17.5 rounded-none border-0 bg-transparent px-4 pt-3.5 pb-1 leading-relaxed focus-visible:ring-0 focus-visible:ring-offset-0"
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Add a comment, answer a question, or steer the agent"
          rows={1}
          value={body}
        />
        <div className="flex items-center gap-2 px-3 pb-3">
          {reply.error && (
            <span className="text-danger min-w-0 truncate text-xs" role="alert">
              {errorMessage(reply.error)}
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            <Button
              className="h-8 rounded-full px-3"
              disabled={!ready}
              onClick={() => send(true)}
              size="sm"
              title="Reply and pause the task"
              type="button"
              variant="outline"
            >
              <Pause className="size-3.5" />
              Reply and hold
            </Button>
            <Button
              aria-label="Send reply"
              className="rounded-full"
              disabled={!ready}
              size="icon-sm"
              title="Reply (Enter). Shift+Enter for a new line."
              type="submit"
            >
              <ArrowUp className="size-4" />
            </Button>
          </div>
        </div>
      </form>
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
  const { data: agents } = useAgentList(orgSlug)
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

  const send = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (resolve.isPending) return
    const answer = String(
      new FormData(event.currentTarget).get('answer') ?? '',
    ).trim()
    if (answer) submit({ answer, status: 'answered' })
  }

  const asker = agents?.find((a) => a.id === r.opened_by) ?? {
    id: r.opened_by ?? '',
    name: actorName(r.opened_by),
  }

  if (r.status !== 'open' || taken) {
    const outcome = (taken?.status ?? r.status) as TaskRequestView['status']
    const Outcome = OUTCOME[outcome] ?? {
      icon: Check,
      tone: 'text-secondary',
    }
    const by = taken?.by ?? r.resolved_by
    return (
      <div className="border-secondary flex flex-col gap-2.5 rounded-lg border px-4 py-3">
        <div className="text-secondary flex items-start gap-2.5 text-sm">
          <AgentMark agent={asker} className="mt-px" />
          <span className="line-clamp-2 min-w-0 flex-1 wrap-break-word">
            {r.title}
          </span>
        </div>
        <div className="flex items-start gap-2.5">
          <span className="flex size-5 shrink-0 items-center justify-center">
            <Outcome.icon className={cn('size-4', Outcome.tone)} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="text-secondary flex min-h-5 flex-wrap items-center gap-x-1.5 text-xs">
              <span>
                {RESOLVED[outcome] ?? outcome}
                {by && ' by'}
              </span>
              {by && (
                <span className="text-primary flex min-w-0 items-center gap-1.5">
                  <PersonMark email={by} title={by} />
                  <span className="truncate">{by}</span>
                </span>
              )}
              {r.resolved_at && !taken && (
                <span className="text-tertiary">
                  · <RelativeTime tooltip={false} value={r.resolved_at} />
                </span>
              )}
            </div>
            {r.answer && !taken && (
              <p className="text-primary text-sm leading-relaxed whitespace-pre-wrap">
                {r.answer}
              </p>
            )}
          </div>
        </div>
      </div>
    )
  }

  const actionable = canResolve && task.status !== 'closed'
  return (
    <section
      aria-label="Waiting on you"
      className="border-amber-border bg-primary flex flex-col gap-4 rounded-lg border p-4"
    >
      <header className="flex items-center gap-2.5">
        <AgentMark agent={asker} />
        <span className="min-w-0 truncate text-sm font-medium">
          {asker.name}
        </span>
        <span className="text-tertiary shrink-0 text-xs">
          asked <RelativeTime tooltip={false} value={r.opened_at} />
        </span>
        <span className="bg-amber-bg text-amber-text ml-auto flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium">
          <Hand className="size-3.5" />
          Waiting on you
        </span>
      </header>
      <div className="flex flex-col gap-1.5">
        <h3 className="text-sm leading-relaxed font-medium text-pretty wrap-break-word">
          {r.title}
        </h3>
        {r.why && (
          <p className="text-secondary text-sm leading-relaxed whitespace-pre-wrap">
            {r.why}
          </p>
        )}
      </div>
      {r.artifacts.length > 0 && (
        <div className="flex flex-col gap-2">
          {r.artifacts.map((a, i) => (
            <div
              className="border-secondary bg-secondary truncate rounded-md border px-3 py-2 font-mono text-xs"
              key={i}
            >
              {label(a)}
            </div>
          ))}
        </div>
      )}
      {actionable && r.kind === 'approval' && (
        <div className="flex items-center gap-2">
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
        <Questionnaire onSubmit={send}>
          <QuestionnaireItem name="answer" required>
            <QuestionnaireTitle className="sr-only">
              {r.title}
            </QuestionnaireTitle>
            <QuestionnaireChoices>
              {r.options.map((o, i) => (
                <QuestionnaireChoice key={i} value={label(o)}>
                  {label(o)}
                </QuestionnaireChoice>
              ))}
              <QuestionnaireInput
                aria-label="Answer"
                placeholder={
                  r.options.length > 0
                    ? 'Something else…'
                    : 'Answer in your own words'
                }
              />
            </QuestionnaireChoices>
            <QuestionnaireError>
              Pick an answer or write one.
            </QuestionnaireError>
          </QuestionnaireItem>
          <QuestionnaireActions>
            <QuestionnaireSubmit disabled={resolve.isPending}>
              Send answer
            </QuestionnaireSubmit>
          </QuestionnaireActions>
        </Questionnaire>
      )}
      {resolve.error && (
        <p className="text-danger text-xs" role="alert">
          {errorMessage(resolve.error)}
        </p>
      )}
    </section>
  )
}

/** A string option or artifact as text; anything else as JSON. */
function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
