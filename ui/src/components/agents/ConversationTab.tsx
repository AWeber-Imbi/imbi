import { type ReactNode, useMemo, useState } from 'react'

import {
  Bot,
  Brain,
  Check,
  Copy,
  FilePen,
  FileText,
  ListTodo,
  Plug,
  SquareTerminal,
  TriangleAlert,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Marker, MarkerContent, MarkerIcon } from '@/components/ui/marker'
import { Message, MessageContent, MessageHeader } from '@/components/ui/message'
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from '@/components/ui/trace'
import type { AgentTask } from '@/types'

import { conversationMarkdown, turnFooter } from './conversationMarkdown'
import {
  canCollapseTurn,
  type ConversationMode,
  groupOpenByDefault,
  groupSummary,
  isConversationMode,
  turnOpenByDefault,
  turnTitle,
  useConversationMode,
  useFoldState,
} from './conversationMode'
import {
  entryKey,
  type ProcessGroup,
  type Turn,
  turns,
} from './conversationTurns'
import { Prose, Todos, ToolReadable } from './taskEntryViews'
import { formatElapsed, isFailed, type TaskRequestView } from './taskEvents'
import { RequestCard } from './TaskTabs'
import { systemText, useActorName } from './taskText'
import { isDenied, isError, timeline, type TimelineEntry } from './taskTimeline'
import {
  type Family,
  familyOf,
  isRecord,
  label,
  toolLabel,
  toolSummary,
} from './toolCalls'

interface Ctx {
  isOpen: (id: string, byDefault: boolean) => boolean
  mode: ConversationMode
  orgSlug: string
  requests: TaskRequestView[]
  setOpen: (id: string, open: boolean) => void
  task: AgentTask
}

const FAMILY_ICON: Record<Family, ReactNode> = {
  agent: <Bot />,
  edit: <FilePen />,
  mcp: <Plug />,
  read: <FileText />,
  shell: <SquareTerminal />,
}

const MODE_LABEL: Record<ConversationMode, string> = {
  compact: 'Compact',
  standard: 'Standard',
  verbose: 'Verbose',
}

/**
 * The task as a transcript: one turn per exchange, its work folded under
 * a "Worked for" line, and the agent's replies always in view.
 */
export function ConversationTab({
  events,
  orgSlug,
  requests,
  task,
}: {
  events: Parameters<typeof timeline>[0]
  orgSlug: string
  requests: TaskRequestView[]
  task: AgentTask
}) {
  const [mode, setMode] = useConversationMode()
  const [isOpen, setOpen] = useFoldState()
  const list = useMemo(
    () =>
      turns(timeline(events), {
        failed: isFailed(task),
        live: task.status !== 'closed',
      }),
    [events, task],
  )
  const ctx: Ctx = { isOpen, mode, orgSlug, requests, setOpen, task }

  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="border-tertiary flex shrink-0 items-center gap-2 border-b px-6 py-2">
          <ToggleGroup
            aria-label="Detail"
            onValueChange={(value) => {
              if (isConversationMode(value)) setMode(value)
            }}
            size="sm"
            type="single"
            value={mode}
            variant="outline"
          >
            {(Object.keys(MODE_LABEL) as ConversationMode[]).map((m) => (
              <ToggleGroupItem key={m} value={m}>
                {MODE_LABEL[m]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <CopyButton list={list} task={task} />
        </div>
        <MessageScroller className="flex-1">
          <MessageScrollerViewport aria-label="Conversation">
            <MessageScrollerContent className="mx-auto w-full max-w-3xl px-6 py-5">
              {list.length === 0 ? (
                <p className="text-tertiary text-sm">No conversation yet.</p>
              ) : (
                list.map((turn) => (
                  <TurnView ctx={ctx} key={turn.id} turn={turn} />
                ))
              )}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton />
        </MessageScroller>
      </div>
    </MessageScrollerProvider>
  )
}

function CallRow({ ctx, entry }: { ctx: Ctx; entry: TimelineEntry }) {
  const e = entry.event
  const p = e?.payload ?? {}
  const tool = e ? String(p.tool ?? 'tool') : 'Task'
  const family = familyOf(tool)
  const argsText = typeof p.arguments === 'string' ? p.arguments : null
  const args = isRecord(p.arguments) ? p.arguments : {}
  const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const closed = ctx.task.status === 'closed'
  const summary = e
    ? (argsText?.slice(0, 200) ?? toolSummary(tool, args))
    : closed
      ? 'Did not finish'
      : 'Running…'
  const status = isError(entry)
    ? 'error'
    : !e && !closed
      ? 'running'
      : undefined
  const key = entryKey(entry)
  return (
    <TraceCollapsible
      onOpenChange={(open) => ctx.setOpen(key, open)}
      open={ctx.isOpen(key, false)}
    >
      <TraceCollapsibleTrigger>
        <TraceLine status={status}>
          <TraceIcon>{FAMILY_ICON[family]}</TraceIcon>
          <TraceTitle>
            <span className="font-medium">{toolLabel(tool)}</span>{' '}
            <span className="font-mono text-xs">{summary}</span>
          </TraceTitle>
          {isDenied(p) && <TraceDescription>denied by policy</TraceDescription>}
          {ms != null && (
            <TraceDescription>
              {ms < 1000 ? `${ms}ms` : formatElapsed(ms)}
            </TraceDescription>
          )}
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="flex flex-col gap-2">
        {e && (
          <ToolReadable
            args={args}
            argsText={argsText}
            error={p.is_error === true}
            family={family}
            result={p.result == null ? '' : label(p.result)}
          />
        )}
        {entry.children.length > 0 && (
          <div className="border-accent/40 flex flex-col gap-2 border-l-2 pl-3">
            <Marker className="text-accent text-xs">
              <MarkerIcon>
                <Bot />
              </MarkerIcon>
              <MarkerContent>
                {String(args.subagent_type ?? 'Subagent')} subagent ·{' '}
                {entry.children.length} steps
              </MarkerContent>
            </Marker>
            <Trace>
              {entry.children.map((child) => (
                <WorkRow ctx={ctx} entry={child} key={entryKey(child)} />
              ))}
            </Trace>
          </div>
        )}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

function CopyButton({ list, task }: { list: Turn[]; task: AgentTask }) {
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<null | string>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(conversationMarkdown(task, list))
      setError(null)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not copy.')
    }
  }
  return (
    <div className="ml-auto flex items-center gap-2">
      {error && (
        <span className="text-danger text-xs" role="alert">
          {error}
        </span>
      )}
      <Button
        onClick={copy}
        size="sm"
        title="Copies the events loaded so far"
        type="button"
        variant="outline"
      >
        {copied ? (
          <Check data-icon="inline-start" />
        ) : (
          <Copy data-icon="inline-start" />
        )}
        {copied ? 'Copied' : 'Copy as Markdown'}
      </Button>
    </div>
  )
}

function GroupView({
  ctx,
  group,
  turn,
}: {
  ctx: Ctx
  group: ProcessGroup
  turn: Turn
}) {
  const failed = group.entries.some(isError)
  return (
    <Trace>
      <TraceCollapsible
        onOpenChange={(open) => ctx.setOpen(group.id, open)}
        open={ctx.isOpen(group.id, groupOpenByDefault(group, turn, ctx.mode))}
      >
        <TraceCollapsibleTrigger>
          <TraceLine status={failed ? 'error' : undefined}>
            <TraceTitle>{groupSummary(group)}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>
            {group.entries.map((entry) => (
              <WorkRow ctx={ctx} entry={entry} key={entryKey(entry)} />
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  )
}

function PersonMessage({ ctx, entry }: { ctx: Ctx; entry: TimelineEntry }) {
  const actorName = useActorName(ctx.orgSlug)
  const e = entry.event
  if (!e) return null
  const body =
    typeof e.payload.body === 'string' && e.payload.body
      ? e.payload.body
      : systemText(e)
  return (
    <Message align="end">
      <MessageContent>
        <MessageHeader>{actorName(e.actor_id)}</MessageHeader>
        <div className="bg-secondary max-w-[85%] self-end rounded-xl px-3.5 py-2.5">
          <Prose>{body}</Prose>
          {typeof e.payload.decision === 'string' && (
            <p className="text-secondary mt-1 text-sm">{e.payload.decision}</p>
          )}
        </div>
      </MessageContent>
    </Message>
  )
}

function RequestItem({ ctx, entry }: { ctx: Ctx; entry: TimelineEntry }) {
  const e = entry.event
  const request = ctx.requests.find((r) => r.id === e?.payload.request_id)
  if (request?.status === 'open')
    return (
      <RequestCard orgSlug={ctx.orgSlug} request={request} task={ctx.task} />
    )
  return (
    <Trace>
      <TraceLine>
        <TraceTitle>{e ? systemText(e) : ''}</TraceTitle>
      </TraceLine>
    </Trace>
  )
}

function TurnHeader({
  ctx,
  open,
  turn,
}: {
  ctx: Ctx
  open: boolean
  turn: Turn
}) {
  const status =
    turn.status === 'running'
      ? 'running'
      : turn.status === 'failed'
        ? 'error'
        : undefined
  const line = (
    <TraceLine status={status}>
      <TraceTitle>{turnTitle(turn)}</TraceTitle>
    </TraceLine>
  )
  return (
    <Trace>
      {canCollapseTurn(turn) ? (
        <TraceCollapsible
          onOpenChange={(next) => ctx.setOpen(turn.id, next)}
          open={open}
        >
          <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        </TraceCollapsible>
      ) : (
        <div>{line}</div>
      )}
    </Trace>
  )
}

function TurnView({ ctx, turn }: { ctx: Ctx; turn: Turn }) {
  const open =
    !canCollapseTurn(turn) ||
    ctx.isOpen(turn.id, turnOpenByDefault(turn, ctx.mode))
  const hasWork = turn.items.some((i) => i.kind === 'group')
  const footer = hasWork ? turnFooter(turn) : null
  return (
    <MessageScrollerItem messageId={turn.id} scrollAnchor>
      <div className="flex flex-col gap-4">
        {turn.opening.map((entry) => (
          <PersonMessage ctx={ctx} entry={entry} key={entry.id} />
        ))}
        {(hasWork || turn.status !== 'done') && (
          <TurnHeader ctx={ctx} open={open} turn={turn} />
        )}
        {turn.items.map((item) => {
          switch (item.kind) {
            case 'group':
              return open ? (
                <GroupView ctx={ctx} group={item} key={item.id} turn={turn} />
              ) : null
            case 'input':
              return item.entry.event?.type === 'request.opened' ? (
                <RequestItem ctx={ctx} entry={item.entry} key={item.id} />
              ) : (
                <PersonMessage ctx={ctx} entry={item.entry} key={item.id} />
              )
            case 'note':
              return (
                <Trace key={item.id}>
                  <TraceLine>
                    <TraceTitle>
                      {item.entry.event ? systemText(item.entry.event) : ''}
                    </TraceTitle>
                  </TraceLine>
                </Trace>
              )
            case 'reply':
              return (
                <Message key={item.id}>
                  <MessageContent>
                    <Prose>
                      {String(item.entry.event?.payload.body ?? '')}
                    </Prose>
                  </MessageContent>
                </Message>
              )
          }
        })}
        {footer && (
          <Marker className="text-xs">
            <MarkerContent>{footer}</MarkerContent>
          </Marker>
        )}
      </div>
    </MessageScrollerItem>
  )
}

/** One step inside a process group: a call, a thought, a plan, a note. */
function WorkRow({ ctx, entry }: { ctx: Ctx; entry: TimelineEntry }) {
  const e = entry.event
  if (!e || e.type === 'tool.called') return <CallRow ctx={ctx} entry={entry} />
  const body = String(e.payload.body ?? '')
  if (e.type === 'turn' && e.payload.kind === 'warning')
    return (
      <TraceLine status="error">
        <TraceIcon>
          <TriangleAlert />
        </TraceIcon>
        <TraceTitle>{body}</TraceTitle>
      </TraceLine>
    )
  if (e.type === 'turn' || e.type === 'todos.updated')
    return (
      <TraceCollapsible
        onOpenChange={(open) => ctx.setOpen(entry.id, open)}
        open={ctx.isOpen(entry.id, false)}
      >
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              {e.type === 'turn' ? <Brain /> : <ListTodo />}
            </TraceIcon>
            <TraceTitle>
              {e.type === 'turn'
                ? `Thought: ${body.split('\n')[0]}`
                : 'Updated the plan'}
            </TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          {e.type === 'turn' ? <Prose>{body}</Prose> : <Todos event={e} />}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    )
  return (
    <TraceLine>
      <TraceTitle>{systemText(e)}</TraceTitle>
    </TraceLine>
  )
}
