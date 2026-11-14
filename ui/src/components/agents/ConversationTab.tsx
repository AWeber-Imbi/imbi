import { type ReactNode, useMemo, useRef, useState } from 'react'

import {
  Bot,
  Brain,
  ChevronRight,
  FilePen,
  FileText,
  FoldHorizontal,
  List,
  ListCollapse,
  ListTodo,
  ListTree,
  MessageSquare,
  Plug,
  Search,
  SquareTerminal,
  TriangleAlert,
  UnfoldHorizontal,
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
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

import {
  conversationMarkdown,
  resolution,
  turnFooter,
} from './conversationMarkdown'
import {
  canCollapseTurn,
  type ConversationMode,
  type ConversationWidth,
  groupErrors,
  groupOpenByDefault,
  groupSummary,
  turnOpenByDefault,
  turnTitle,
  useConversationMode,
  useConversationWidth,
  useFoldState,
} from './conversationMode'
import {
  entryKey,
  type ProcessGroup,
  type Turn,
  turns,
} from './conversationTurns'
import { Prose, Todos, ToolReadable } from './taskEntryViews'
import {
  formatElapsed,
  isFailed,
  type TaskRequestView,
  TRIGGERS,
} from './taskEvents'
import {
  matches,
  ToolbarSearch,
  useSearchHighlight,
  useTaskSearch,
} from './taskSearch'
import { RequestCard } from './TaskTabs'
import { systemText, useActorName } from './taskText'
import { isDenied, isError, timeline, type TimelineEntry } from './taskTimeline'
import {
  TaskCopyMenu,
  TaskToolbar,
  ToolbarChoice,
  type ToolbarOption,
} from './TaskToolbar'
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
  search: <Search />,
  shell: <SquareTerminal />,
}

const ASK_PREVIEW = 600

const MODES: ToolbarOption<ConversationMode>[] = [
  {
    hint: 'Compact: replies, with the work folded',
    icon: ListCollapse,
    label: 'Compact',
    value: 'compact',
  },
  {
    hint: 'Standard: replies and work summaries',
    icon: List,
    label: 'Standard',
    value: 'standard',
  },
  {
    hint: 'Verbose: every work group open',
    icon: ListTree,
    label: 'Verbose',
    value: 'verbose',
  },
]

const WIDTHS: ToolbarOption<ConversationWidth>[] = [
  {
    hint: 'Narrow: a readable column',
    icon: FoldHorizontal,
    label: 'Narrow',
    value: 'narrow',
  },
  {
    hint: 'Wide: the full pane',
    icon: UnfoldHorizontal,
    label: 'Wide',
    value: 'wide',
  },
]

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
  const [width, setWidth] = useConversationWidth()
  const [isOpen, setOpen] = useFoldState()
  const list = useMemo(
    () =>
      turns(timeline(events), {
        failed: isFailed(task),
        live: task.status === 'running',
      }),
    [events, task],
  )
  const [query, setQuery] = useTaskSearch()
  const root = useRef<HTMLDivElement>(null)
  useSearchHighlight(root, query)
  const searching = query.trim() !== ''
  const shown = useMemo(
    () => (searching ? list.filter((t) => matches(turnText(t), query)) : list),
    [list, query, searching],
  )
  const ctx: Ctx = useMemo(
    () => ({
      isOpen: searching ? () => true : isOpen,
      mode: searching ? 'verbose' : mode,
      orgSlug,
      requests,
      setOpen,
      task,
    }),
    [isOpen, mode, orgSlug, requests, searching, setOpen, task],
  )

  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <div className="flex min-h-0 flex-1 flex-col" ref={root}>
        <TaskToolbar label="Conversation">
          <ToolbarChoice
            label="Detail"
            onChange={setMode}
            options={MODES}
            value={mode}
          />
          <ToolbarChoice
            label="Width"
            onChange={setWidth}
            options={WIDTHS}
            value={width}
          />
          <div className="ml-auto flex min-w-40 flex-1 items-center justify-end gap-2">
            <ToolbarSearch
              label="Search conversation"
              onChange={setQuery}
              value={query}
            />
            <TaskCopyMenu events={events} task={task} />
          </div>
        </TaskToolbar>
        <MessageScroller className="flex-1">
          <MessageScrollerViewport aria-label="Conversation">
            <MessageScrollerContent
              className={cn(
                'w-full px-10 py-5',
                width === 'narrow' && 'mx-auto max-w-3xl',
              )}
            >
              <TaskAsk ctx={ctx} first={list[0]} />
              {shown.length === 0 ? (
                <p className="text-tertiary text-sm">
                  {searching
                    ? `No turns match “${query.trim()}”.`
                    : 'No conversation yet.'}
                </p>
              ) : (
                shown.map((turn) => (
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
  const running = ctx.task.status === 'running'
  const summary = e
    ? (argsText?.slice(0, 200) ?? toolSummary(tool, args))
    : running
      ? 'Running…'
      : ctx.task.status === 'closed'
        ? 'Did not finish'
        : 'Not finished yet'
  const status = isError(entry)
    ? 'error'
    : !e && running
      ? 'running'
      : undefined
  const key = entryKey(entry)
  const steps = entry.children.filter(
    (child) => child.event?.type !== 'usage.reported',
  ).length
  const agent =
    typeof args.subagent_type === 'string' && args.subagent_type
      ? `${args.subagent_type} subagent`
      : 'Subagent'
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
                {`${agent} · ${steps} ${steps === 1 ? 'step' : 'steps'}`}
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

function GroupView({
  ctx,
  group,
  turn,
}: {
  ctx: Ctx
  group: ProcessGroup
  turn: Turn
}) {
  const failed = groupErrors(group) > 0
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
  const { answer, constraints } = resolution(e)
  return (
    <Message align="end">
      <MessageContent>
        <MessageHeader>{actorName(e.actor_id)}</MessageHeader>
        <div className="bg-secondary max-w-[85%] self-end rounded-xl px-3.5 py-2.5">
          <Prose>{body}</Prose>
          {answer && <Prose>{answer}</Prose>}
          {constraints.length > 0 && (
            <ul className="text-secondary mt-1 list-disc pl-5 text-sm">
              {constraints.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      </MessageContent>
    </Message>
  )
}

/** The start and the close are said by the footer and the outcome. */
function quiet(e: AgentTaskEvent | null | undefined): boolean {
  if (e?.type !== 'state.changed') return false
  const { from, to } = e.payload
  return to === 'closed' || (from === 'queued' && to === 'running')
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

function searchText(entry: TimelineEntry): string {
  return [
    ...values(entry.event?.payload ?? {}),
    ...entry.children.map(searchText),
  ].join(' ')
}

/** What started the task, as the first message, unless a person already said it. */
function TaskAsk({ ctx, first }: { ctx: Ctx; first?: Turn }) {
  const actorName = useActorName(ctx.orgSlug)
  const [all, setAll] = useState(false)
  const { task } = ctx
  const body = (task.description || task.title || '').trim()
  const said = first?.opening.some(
    (entry) =>
      entry.event?.actor_kind === 'human' &&
      String(entry.event.payload.body ?? '').trim() === body,
  )
  if (!body || said) return null
  const source = TRIGGERS[task.origin.kind].label
  const long = body.length > ASK_PREVIEW
  return (
    <Message align="end" className="mb-4">
      <MessageContent>
        <MessageHeader>
          {task.origin.user
            ? `${source} · ${actorName(task.origin.user)}`
            : source}
        </MessageHeader>
        <div className="bg-secondary flex max-w-[85%] flex-col items-start gap-1 self-end rounded-xl px-3.5 py-2.5">
          <Prose>
            {long && !all ? `${body.slice(0, ASK_PREVIEW)}…` : body}
          </Prose>
          {long && (
            <Button onClick={() => setAll(!all)} size="sm" variant="link">
              {all ? 'Show less' : 'Show all'}
            </Button>
          )}
        </div>
      </MessageContent>
    </Message>
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
        <button
          aria-expanded={open}
          className="group/trace-collapsible-trigger text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 has-[[data-status=error]]:text-destructive flex w-fit max-w-full min-w-0 cursor-pointer items-center gap-1 rounded-md text-left transition-colors outline-none focus-visible:ring-3"
          onClick={() => ctx.setOpen(turn.id, !open)}
          type="button"
        >
          {line}
          <TraceIcon className="transition-transform group-aria-expanded/trace-collapsible-trigger:rotate-90">
            <ChevronRight />
          </TraceIcon>
        </button>
      ) : (
        <div>{line}</div>
      )}
    </Trace>
  )
}

/** The turn as Markdown plus every value its events hold, for search. */
function turnText(turn: Turn): string {
  const entries = [
    ...turn.opening,
    ...turn.items.flatMap((item) =>
      item.kind === 'group' ? item.entries : [item.entry],
    ),
  ]
  return [
    conversationMarkdown({ title: 'x' }, [turn]).replace(
      /^# x\s+## Turn 1\s+/,
      '',
    ),
    ...entries.map(searchText),
  ].join(' ')
}

function TurnView({ ctx, turn }: { ctx: Ctx; turn: Turn }) {
  const open =
    !canCollapseTurn(turn) ||
    ctx.isOpen(turn.id, turnOpenByDefault(turn, ctx.mode))
  const actorName = useActorName(ctx.orgSlug)
  const hasWork = turn.items.some((i) => i.kind === 'group')
  const footer = turnFooter(turn)
  const firstReply = turn.items.find((i) => i.kind === 'reply')?.id
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
              return quiet(item.entry.event) ? null : (
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
                    {item.id === firstReply && (
                      <MessageHeader className="px-0">
                        {actorName(ctx.task.agent_id)} v{ctx.task.agent_version}
                      </MessageHeader>
                    )}
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

function values(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (typeof value === 'number') return [String(value)]
  if (Array.isArray(value)) return value.flatMap(values)
  if (value && typeof value === 'object')
    return Object.values(value).flatMap(values)
  return []
}

/** One step inside a process group: a call, a thought, a plan, a note. */
function WorkRow({ ctx, entry }: { ctx: Ctx; entry: TimelineEntry }) {
  const e = entry.event
  if (!e || e.type === 'tool.called') return <CallRow ctx={ctx} entry={entry} />
  if (e.type === 'usage.reported') return null
  const body = String(e.payload.body ?? '')
  const thought = e.payload.kind === 'thinking'
  if (e.type === 'turn' && e.payload.kind === 'warning')
    return (
      <TraceLine className="items-start" status="error">
        <TraceIcon className="mt-0.5">
          <TriangleAlert />
        </TraceIcon>
        <TraceTitle className="wrap-break-word text-clip whitespace-pre-wrap">
          {body}
        </TraceTitle>
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
              {e.type !== 'turn' ? (
                <ListTodo />
              ) : thought ? (
                <Brain />
              ) : (
                <MessageSquare />
              )}
            </TraceIcon>
            <TraceTitle>
              {e.type !== 'turn'
                ? 'Updated the plan'
                : thought
                  ? `Thought: ${body.split('\n')[0]}`
                  : body.split('\n')[0]}
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
