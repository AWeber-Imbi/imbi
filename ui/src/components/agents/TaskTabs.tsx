import {
  type Dispatch,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
  type SetStateAction,
  useState,
} from 'react'

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
import { resolveTicketRequest } from '@/api/endpoints'
import { StageCardShell } from '@/components/deployments/StageCardShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Questionnaire,
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
import { useTheme } from '@/contexts/ThemeContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { deriveChipColors } from '@/lib/chip-colors'
import type { Ticket, TicketEvent, TicketResolve } from '@/types'

import { useAgentList } from './agentQueries'
import { checksFrom, type TaskRequestView } from './taskEvents'
import { AgentMark, PersonMark } from './TaskFilterBar'
import { errorMessage, type TaskReply, useTicketMutation } from './taskQueries'
import { RESOLVED, useActorName } from './taskText'

const HONEY = '#C9A227'
const STONE = '#7A7873'

const OUTCOME: Partial<
  Record<TaskRequestView['status'], { icon: LucideIcon; swatch: string }>
> = {
  answered: { icon: Check, swatch: '#6B9A3F' },
  approved: { icon: Check, swatch: '#6B9A3F' },
  expired: { icon: Clock, swatch: STONE },
  rejected: { icon: X, swatch: '#C86B5E' },
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
export function ChecksTab({ events }: { events: TicketEvent[] }) {
  const checks = checksFrom(events)
  if (checks.length === 0) {
    return <p className="text-tertiary p-6 text-sm">No checks reported yet.</p>
  }
  return (
    <div>
      <p className="border-tertiary text-tertiary border-b px-6 py-3 text-xs">
        Signals the agent and its subagents report against this ticket
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
  body,
  onBodyChange,
  orgSlug,
  pointer,
  reply,
}: {
  body: string
  onBodyChange: Dispatch<SetStateAction<string>>
  orgSlug: string
  pointer: RefObject<null | string>
  reply: TaskReply
}) {
  const canManage = useHasPermission('ticket:manage', orgSlug)
  if (!canManage) return null
  const ready = body.trim() !== '' && !reply.isPending
  const send = (hold: boolean) => {
    if (!ready) return
    const text = body
    reply
      .mutateAsync({ hold, text })
      .then(() => onBodyChange((now) => (now === text ? '' : now)))
      .catch(() => undefined)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const touch =
      pointer.current === null
        ? !!window.matchMedia?.('(pointer: coarse)').matches
        : pointer.current !== 'mouse'
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      touch
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
          onChange={(e) => onBodyChange(e.target.value)}
          onKeyDown={onKeyDown}
          onPointerDown={(e) => {
            pointer.current = e.pointerType
          }}
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
              title="Reply and pause the ticket"
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
  task: Ticket
}) {
  if (requests.length === 0) {
    return (
      <p className="text-tertiary p-6 text-sm">
        This ticket has not asked for input.
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
  task: Ticket
}) {
  const canResolve = useHasPermission('ticket:resolve', orgSlug)
  const actorName = useActorName(orgSlug)
  const { isDarkMode } = useTheme()
  const { data: agents } = useAgentList(orgSlug)
  // Someone else resolved it first: collapse in place (I4).
  const [taken, setTaken] = useState<null | { by: string; status: string }>(
    null,
  )
  const resolve = useTicketMutation(
    orgSlug,
    task.short_id,
    (resolution: TicketResolve) =>
      resolveTicketRequest(orgSlug, task.short_id, r.id, resolution),
  )
  const submit = (resolution: TicketResolve) =>
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
    const Outcome = OUTCOME[outcome] ?? { icon: Check, swatch: STONE }
    const by = taken?.by ?? r.resolved_by
    const answer = taken ? null : r.answer
    return (
      <StageCardShell
        accent={deriveChipColors(Outcome.swatch, isDarkMode)}
        icon={Outcome.icon}
        subtitle={
          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
            {RESOLVED[outcome] ?? outcome}
            {by && (
              <>
                {' by'}
                <PersonMark email={by} title={by} />
                <span className="truncate">{by}</span>
              </>
            )}
            {r.resolved_at && !taken && (
              <>
                <span aria-hidden="true">·</span>
                <RelativeTime tooltip={false} value={r.resolved_at} />
              </>
            )}
          </span>
        }
        title={<span className="line-clamp-2 wrap-break-word">{r.title}</span>}
      >
        {answer ? (
          <div className="px-4 py-3">
            <p className="text-tertiary mb-1.5 text-xs tracking-wider uppercase">
              Answer
            </p>
            <p className="text-sm leading-relaxed wrap-break-word whitespace-pre-wrap">
              {answer}
            </p>
          </div>
        ) : null}
      </StageCardShell>
    )
  }

  const actionable = canResolve && task.status !== 'closed'
  const feedback = actionable && r.kind === 'feedback'
  const body = (
    <div className="flex flex-col gap-4 px-4 py-4">
      <section>
        <p className="text-tertiary mb-1.5 text-xs tracking-wider uppercase">
          {r.kind === 'approval' ? 'Approval requested' : 'Question'}
        </p>
        <h3 className="text-sm leading-relaxed font-medium text-pretty wrap-break-word">
          {r.title}
        </h3>
        {r.why && (
          <p className="text-secondary mt-1 text-sm leading-relaxed whitespace-pre-wrap">
            {r.why}
          </p>
        )}
      </section>
      {r.artifacts.length > 0 && (
        <section>
          <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
            Artifacts
          </p>
          <div className="border-tertiary divide-tertiary divide-y overflow-hidden rounded-md border">
            {r.artifacts.map((a, i) => (
              <div className="truncate px-3 py-2 font-mono text-xs" key={i}>
                {label(a)}
              </div>
            ))}
          </div>
        </section>
      )}
      {feedback && (
        <QuestionnaireItem name="answer" required>
          <QuestionnaireTitle className="text-tertiary text-xs font-normal tracking-wider uppercase">
            {r.options.length > 0 ? 'Pick an answer' : 'Your answer'}
          </QuestionnaireTitle>
          <QuestionnaireChoices className="border-tertiary gap-0 overflow-hidden rounded-md border">
            {r.options.map((o, i) => (
              <QuestionnaireChoice
                className="border-tertiary data-checked:border-tertiary rounded-none border-0 border-b"
                key={i}
                value={label(o)}
              >
                {label(o)}
              </QuestionnaireChoice>
            ))}
            <QuestionnaireInput
              aria-label="Answer"
              className="rounded-none border-0 focus-visible:ring-0"
              placeholder={
                r.options.length > 0
                  ? 'Something else…'
                  : 'Answer in your own words'
              }
            />
          </QuestionnaireChoices>
          <QuestionnaireError className="text-xs">
            Pick an answer or write one.
          </QuestionnaireError>
        </QuestionnaireItem>
      )}
    </div>
  )
  const footer =
    actionable || resolve.error ? (
      <div className="border-tertiary flex items-center justify-end gap-2 border-t px-4 py-3">
        {resolve.error && (
          <p className="text-danger mr-auto text-xs" role="alert">
            {errorMessage(resolve.error)}
          </p>
        )}
        {actionable && r.kind === 'approval' && (
          <>
            <Button
              disabled={resolve.isPending}
              onClick={() => submit({ status: 'rejected' })}
              size="sm"
              variant="ghost"
            >
              Reject
            </Button>
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
          </>
        )}
        {feedback && (
          <QuestionnaireSubmit disabled={resolve.isPending}>
            Send answer
          </QuestionnaireSubmit>
        )}
      </div>
    ) : null
  return (
    <section aria-label="Waiting on you">
      <StageCardShell
        accent={deriveChipColors(HONEY, isDarkMode)}
        icon={Hand}
        subtitle={
          <span className="flex min-w-0 items-center gap-1.5">
            <AgentMark agent={asker} />
            <span className="truncate">{asker.name}</span>
            <span className="shrink-0">
              asked <RelativeTime tooltip={false} value={r.opened_at} />
            </span>
          </span>
        }
        title="Waiting on you"
      >
        {feedback ? (
          <Questionnaire className="gap-0" onSubmit={send}>
            {body}
            {footer}
          </Questionnaire>
        ) : (
          <>
            {body}
            {footer}
          </>
        )}
      </StageCardShell>
    </section>
  )
}

/** A string option or artifact as text; anything else as JSON. */
function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
