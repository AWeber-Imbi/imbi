import { useEffect, useMemo, useRef, useState } from 'react'

import { Link, useLocation, useNavigate } from 'react-router-dom'

import { ChevronRight, Search, TriangleAlert, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useFollowBottom } from '@/hooks/useFollowBottom'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

import { elapsed } from './conversationMode'
import {
  AgentMessage,
  HumanMessage,
  Pane,
  Prose,
  Todos,
  ToolReadable,
} from './taskEntryViews'
import { formatElapsed, type TaskRequestView } from './taskEvents'
import { RequestCard } from './TaskTabs'
import { clock, systemText, useActorName } from './taskText'
import {
  categoryOf,
  countTimeline,
  DEFAULT_FILTERS,
  filterTimeline,
  isDenied,
  isError,
  timeline,
  type TimelineEntry,
  type TimelineFilters,
} from './taskTimeline'
import { findEntry } from './taskTrajectory'
import { TimingOverview } from './TimingOverview'
import {
  FAMILY_TAG,
  familyOf,
  isRecord,
  label,
  toolLabel,
  toolSummary,
} from './toolCalls'

/** The filter chips, in order. */
type ChipKey = 'messages' | 'subagents' | 'system' | 'thinking' | 'tools'

interface RowContext {
  isOpen: (id: string) => boolean
  orgSlug: string
  requests: TaskRequestView[]
  selected: null | number
  task: AgentTask
  toggle: (id: string) => void
}

/** The spine dot color of each kind of entry. */
const DOT: Record<string, string> = {
  error: 'text-danger',
  human: 'text-info',
  message: 'text-action',
  system: 'text-tertiary',
  thinking: 'text-amber-text-mid',
  tool: 'text-teal',
  warning: 'text-warning',
}

const CHIPS: { dot: string; key: ChipKey; label: string }[] = [
  { dot: DOT.message, key: 'messages', label: 'Messages' },
  { dot: DOT.thinking, key: 'thinking', label: 'Thinking' },
  { dot: DOT.tool, key: 'tools', label: 'Tools' },
  { dot: 'text-accent', key: 'subagents', label: 'Subagents' },
  { dot: DOT.system, key: 'system', label: 'System' },
]

/**
 * The full task log (O5): every turn, tool call, request, and state
 * change in order, with subagent work nested under its call, filters by
 * kind, search, a compact or full level of detail, and `#e<seq>` links.
 */
export function TaskLogTab({
  events,
  orgSlug,
  requests,
  task,
}: {
  events: AgentTaskEvent[]
  orgSlug: string
  requests: TaskRequestView[]
  task: AgentTask
}) {
  const [filters, setFilters] = useState<TimelineFilters>(DEFAULT_FILTERS)
  const [full, setFull] = useState(true)
  // Rows that the reader opened or closed, over the density default.
  const [toggled, setToggled] = useState(new Map<string, boolean>())
  const all = useMemo(() => timeline(events), [events])
  const shown = useMemo(() => filterTimeline(all, filters), [all, filters])
  const counts = useMemo(() => countTimeline(all), [all])
  const listRef = useRef<HTMLDivElement>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const seq = /^#e(\d+)$/.exec(location.hash)?.[1]
  const selected = seq
    ? (findEntry(all, Number(seq))?.event ??
      events.find((e) => e.seq === Number(seq)) ??
      null)
    : null
  const origin = events.length ? Date.parse(events[0].at) : 0
  const close = () =>
    navigate(
      { pathname: location.pathname, search: location.search },
      { replace: true },
    )
  useFollowBottom(listRef, events.length, events.length > 0)

  const isOpen = (id: string) => toggled.get(id) ?? full
  const toggle = (id: string) =>
    setToggled(new Map(toggled).set(id, !isOpen(id)))
  const setDensity = (value: boolean) => {
    setFull(value)
    setToggled(new Map())
  }
  const ctx: RowContext = {
    isOpen,
    orgSlug,
    requests,
    selected: selected?.seq ?? null,
    task,
    toggle,
  }

  useScrollToHash(location.hash, shown.length > 0)

  return (
    <div className="bg-tertiary flex min-h-0 flex-1 flex-col">
      <div className="border-tertiary bg-primary flex shrink-0 flex-wrap items-center gap-2 border-b px-6 py-2.5">
        {CHIPS.map((chip) => (
          <Chip
            count={counts[chip.key]}
            dot={chip.dot}
            key={chip.key}
            label={chip.label}
            onClick={() =>
              setFilters({ ...filters, [chip.key]: !filters[chip.key] })
            }
            pressed={filters[chip.key]}
          />
        ))}
        <span className="h-5 w-px bg-(--ds-border-tertiary)" />
        <Chip
          count={counts.errors}
          danger
          dot={DOT.error}
          label="Errors only"
          onClick={() =>
            setFilters({ ...filters, errorsOnly: !filters.errorsOnly })
          }
          pressed={filters.errorsOnly}
        />
        <SegmentedControl
          ariaLabel="Detail"
          onValueChange={(v) => setDensity(v === 'full')}
          value={full ? 'full' : 'compact'}
        >
          <SegmentedControlItem value="compact">Compact</SegmentedControlItem>
          <SegmentedControlItem value="full">Full</SegmentedControlItem>
        </SegmentedControl>
        <div className="relative ml-auto">
          <Search className="text-tertiary pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            aria-label="Search this task"
            className="h-8 w-48 pl-8 text-xs"
            onChange={(e) => setFilters({ ...filters, query: e.target.value })}
            placeholder="Search this task"
            type="search"
            value={filters.query}
          />
        </div>
      </div>
      <TimingOverview
        entries={all}
        live={task.status === 'running'}
        selected={selected?.seq ?? null}
      />
      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto" ref={listRef}>
          <ol className="py-4">
            {all.length === 0 && (
              <li className="text-tertiary px-6 py-4 text-sm">
                No events yet.
              </li>
            )}
            {all.length > 0 && shown.length === 0 && (
              <li className="text-tertiary px-6 py-4 text-sm">
                Nothing matches these filters.
              </li>
            )}
            {shown.map((entry, i) => (
              <Row
                ctx={ctx}
                entry={entry}
                first={i === 0}
                key={entry.id}
                last={i === shown.length - 1}
              />
            ))}
          </ol>
        </div>
        {selected && (
          <Inspector
            event={selected}
            key={selected.event_id}
            onClose={close}
            orgSlug={orgSlug}
            origin={origin}
          />
        )}
      </div>
    </div>
  )
}

function Chip({
  count,
  danger,
  dot,
  label,
  onClick,
  pressed,
}: {
  count: number
  danger?: boolean
  dot: string
  label: string
  onClick: () => void
  pressed: boolean
}) {
  return (
    <button
      aria-pressed={pressed}
      className={cn(
        'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
        pressed
          ? danger
            ? 'border-transparent bg-danger text-danger'
            : 'border-transparent bg-secondary text-primary'
          : 'border-secondary text-tertiary',
      )}
      onClick={onClick}
      type="button"
    >
      <span
        className={cn(
          'size-2 rounded-full bg-current',
          dot,
          !pressed && 'opacity-40',
        )}
      />
      {label}
      <span className="text-tertiary text-[11px] tabular-nums">{count}</span>
    </button>
  )
}

function dotOf(entry: TimelineEntry): string {
  const e = entry.event
  if (isError(entry)) return DOT.error
  if (!e || e.type === 'tool.called') return DOT.tool
  if (e.type === 'turn') {
    if (e.actor_kind === 'human') return DOT.human
    if (e.payload.kind === 'thinking') return DOT.thinking
    if (e.payload.kind === 'warning') return DOT.warning
    return DOT.message
  }
  if (e.type === 'request.opened') return DOT.warning
  return DOT.system
}

function EntryBody({ ctx, entry }: { ctx: RowContext; entry: TimelineEntry }) {
  const actorName = useActorName(ctx.orgSlug)
  const e = entry.event
  if (!e || e.type === 'tool.called')
    return <ToolCall ctx={ctx} entry={entry} />
  const body = String(e.payload.body ?? '')
  if (e.type === 'turn') {
    if (e.actor_kind === 'human') return <HumanMessage body={body} event={e} />
    if (e.payload.kind === 'thinking')
      return <Thinking ctx={ctx} id={entry.id} text={body} />
    if (e.payload.kind === 'warning')
      return (
        <div className="border-warning bg-warning text-warning flex max-w-[74ch] items-start gap-2 rounded-lg border px-3 py-2 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          {body}
        </div>
      )
    return <AgentMessage body={body} name={actorName(e.actor_id)} />
  }
  if (e.type === 'request.opened') {
    const request = ctx.requests.find((r) => r.id === e.payload.request_id)
    if (request?.status === 'open')
      return (
        <div className="max-w-2xl">
          <RequestCard
            orgSlug={ctx.orgSlug}
            request={request}
            task={ctx.task}
          />
        </div>
      )
  }
  if (e.type === 'todos.updated') return <Todos event={e} />
  return (
    <span className="bg-secondary text-secondary inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs">
      {systemText(e)}
    </span>
  )
}

/** The selected event in full: when it ran, what went in and came out. */
function Inspector({
  event: e,
  onClose,
  orgSlug,
  origin,
}: {
  event: AgentTaskEvent
  onClose: () => void
  orgSlug: string
  origin: number
}) {
  const actorName = useActorName(orgSlug)
  const p = e.payload
  const tool = e.type === 'tool.called' ? String(p.tool ?? 'tool') : null
  const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const at = Date.parse(e.at)
  const input = tool
    ? typeof p.arguments === 'string'
      ? p.arguments
      : JSON.stringify(p.arguments ?? {}, null, 2)
    : typeof p.body === 'string' && p.body
      ? p.body
      : null
  const output = tool && p.result != null ? label(p.result) : null
  const facts: [string, string][] = [
    ['Event', `#${e.seq} · ${e.type}`],
    [
      'Actor',
      e.actor_id ? `${actorName(e.actor_id)} (${e.actor_kind})` : e.actor_kind,
    ],
    ['Time', clock(e.at)],
  ]
  if (ms !== null) {
    facts.push(['Started', clock(new Date(at - ms).toISOString())])
    facts.push(['Duration', ms < 1000 ? `${ms}ms` : formatElapsed(ms)])
  }
  facts.push(['Into task', `+${elapsed(Math.max(0, at - origin))}`])
  if (e.type === 'usage.reported')
    facts.push([
      'Tokens',
      `${String(p.tokens_in ?? 0)} in · ${String(p.tokens_out ?? 0)} out`,
    ])
  const first = input !== null ? 'input' : 'raw'
  return (
    <aside
      aria-label="Event inspector"
      className="border-tertiary bg-primary flex w-[min(26rem,45%)] shrink-0 flex-col overflow-y-auto border-l"
    >
      <div className="border-tertiary flex items-center gap-2 border-b py-1.5 pr-2 pl-4">
        <h3 className="truncate text-sm font-medium">
          {tool ? toolLabel(tool) : e.type}
        </h3>
        <span className="text-tertiary font-mono text-xs">#{e.seq}</span>
        <Button
          aria-label="Close the inspector"
          className="ml-auto"
          onClick={onClose}
          size="icon-sm"
          type="button"
          variant="ghost"
        >
          <X />
        </Button>
      </div>
      <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 px-4 py-3 text-xs">
        {facts.map(([term, value]) => (
          <div className="contents" key={term}>
            <dt className="text-tertiary">{term}</dt>
            <dd className="truncate font-mono">{value}</dd>
          </div>
        ))}
      </dl>
      <Tabs className="flex flex-col gap-2 px-4 pb-4" defaultValue={first}>
        <TabsList>
          {input !== null && <TabsTrigger value="input">Input</TabsTrigger>}
          {output !== null && <TabsTrigger value="output">Output</TabsTrigger>}
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>
        {input !== null && (
          <TabsContent value="input">
            <Pane>{input}</Pane>
          </TabsContent>
        )}
        {output !== null && (
          <TabsContent value="output">
            <Pane>{output}</Pane>
          </TabsContent>
        )}
        <TabsContent value="raw">
          <Pane>{JSON.stringify(e, null, 2)}</Pane>
        </TabsContent>
      </Tabs>
    </aside>
  )
}

/** One entry on the spine: time, a dot colored by kind, and its body. */
function Row({
  ctx,
  entry,
  first,
  last,
}: {
  ctx: RowContext
  entry: TimelineEntry
  first: boolean
  last: boolean
}) {
  const e = entry.event
  const { pathname, search } = useLocation()
  const small = categoryOf(entry) === 'system'
  const selected = e != null && ctx.selected === e.seq
  return (
    <li
      aria-current={selected || undefined}
      className={cn(
        'grid grid-cols-[4.5rem_1.5rem_minmax(0,1fr)] pr-6 pl-2',
        selected && 'bg-secondary',
      )}
      id={e ? `e${e.seq}` : undefined}
    >
      {e ? (
        <Link
          className="text-tertiary hover:text-info pt-3 pr-1.5 text-right font-mono text-[11px] tabular-nums"
          replace
          title="Link to this event"
          to={`${pathname}${search}#e${e.seq}`}
        >
          {clock(e.at)}
        </Link>
      ) : (
        <span />
      )}
      <div className="relative">
        <span
          className={cn(
            'absolute left-tab-y w-0.5 bg-(--ds-border-tertiary)',
            first ? 'top-4' : 'top-0',
            last ? 'h-4' : 'bottom-0',
          )}
        />
        <span
          className={cn(
            'absolute rounded-full bg-current ring-3 ring-(--ds-bg-tertiary)',
            small ? 'top-tab-y left-2 size-2' : 'top-3.25 left-1.5 size-3',
            dotOf(entry),
          )}
        />
      </div>
      <div className={cn('min-w-0 pl-2', small ? 'py-1' : 'py-1.5')}>
        <EntryBody ctx={ctx} entry={entry} />
      </div>
    </li>
  )
}

function Thinking({
  ctx,
  id,
  text,
}: {
  ctx: RowContext
  id: string
  text: string
}) {
  const open = ctx.isOpen(id)
  return (
    <Collapsible
      className="border-amber-border/50 bg-amber-bg/50 rounded-lg border"
      onOpenChange={() => ctx.toggle(id)}
      open={open}
    >
      <CollapsibleTrigger className="text-amber-text flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs">
        <ChevronRight
          className={cn('size-3.5 transition-transform', open && 'rotate-90')}
        />
        <span className="font-semibold">Thinking</span>
        <span className="text-tertiary">
          {text.split(/\s+/).filter(Boolean).length} words
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="text-secondary max-w-[80ch] px-4 pb-3 pl-8 text-[13px] leading-relaxed whitespace-pre-wrap italic">
          {text}
        </p>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** A tool call: one line, and its input and output when open. */
function ToolCall({ ctx, entry }: { ctx: RowContext; entry: TimelineEntry }) {
  const [json, setJson] = useState(false)
  const e = entry.event
  const p = e?.payload ?? {}
  const tool = e ? String(p.tool ?? 'tool') : 'Task'
  const family = familyOf(tool)
  const open = e != null && ctx.isOpen(entry.id)
  // The harness cuts oversized arguments to a JSON string preview.
  const argsText = typeof p.arguments === 'string' ? p.arguments : null
  const args = isRecord(p.arguments) ? p.arguments : {}
  const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const denied = isDenied(p)
  const result = p.result == null ? '' : label(p.result)
  return (
    <Collapsible
      className={cn(
        'overflow-hidden rounded-lg border bg-primary shadow-xs',
        isError(entry) ? 'border-danger' : 'border-tertiary',
      )}
      disabled={!e}
      onOpenChange={() => ctx.toggle(entry.id)}
      open={open}
    >
      <CollapsibleTrigger className="hover:bg-tertiary flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm">
        <ChevronRight
          className={cn(
            'size-3.5 shrink-0 text-tertiary transition-transform',
            open && 'rotate-90',
            !e && 'invisible',
          )}
        />
        <span
          className={cn(
            'shrink-0 rounded px-1.5 py-0.5 font-mono text-[11px] font-medium',
            FAMILY_TAG[family],
          )}
        >
          {toolLabel(tool)}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">
          {e
            ? (argsText?.slice(0, 200) ?? toolSummary(tool, args))
            : ctx.task.status === 'closed'
              ? 'Did not finish'
              : 'Running…'}
        </span>
        {p.is_error === true && !denied && (
          <Badge variant="danger">failed</Badge>
        )}
        {denied && <Badge variant="danger">denied by policy</Badge>}
        {p.mutating === true && !denied && (
          <Badge variant="warning">writes</Badge>
        )}
        {entry.children.length > 0 && (
          <Badge variant="accent">{entry.children.length} steps</Badge>
        )}
        <span className="text-tertiary font-mono text-[11px] whitespace-nowrap tabular-nums">
          {ms == null ? '' : ms < 1000 ? `${ms}ms` : formatElapsed(ms)}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-tertiary flex flex-col gap-2 border-t px-3 pt-2.5 pb-3">
        {denied && (
          <p className="bg-danger text-danger rounded-md px-2.5 py-1.5 text-xs">
            {label(
              (p.policy as { reason?: unknown }).reason ??
                'Denied by policy before it ran.',
            )}
          </p>
        )}
        <div className="flex items-center gap-2">
          <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
            {json ? 'Raw event' : family === 'shell' ? 'Terminal' : 'Input'}
          </span>
          <SegmentedControl
            ariaLabel="View"
            className="ml-auto"
            onValueChange={(v) => setJson(v === 'json')}
            value={json ? 'json' : 'readable'}
          >
            <SegmentedControlItem value="readable">
              Readable
            </SegmentedControlItem>
            <SegmentedControlItem value="json">JSON</SegmentedControlItem>
          </SegmentedControl>
        </div>
        {json ? (
          <Pane>{JSON.stringify(p, null, 2)}</Pane>
        ) : (
          <ToolReadable
            args={args}
            argsText={argsText}
            error={p.is_error === true}
            family={family}
            result={result}
          />
        )}
      </CollapsibleContent>
      {entry.children.length > 0 && (
        <div className="border-accent/40 mx-3 mb-3 ml-6 flex flex-col gap-2 border-l-2 pt-1 pl-3.5">
          <span className="text-accent text-[10.5px] font-semibold tracking-wide uppercase">
            {String(args.subagent_type ?? 'Subagent')}
          </span>
          {entry.children.map((child) => (
            <div
              id={child.event ? `e${child.event.seq}` : undefined}
              key={child.id}
            >
              {child.event?.type === 'turn' ? (
                child.event.payload.kind === 'thinking' ? (
                  <Thinking
                    ctx={ctx}
                    id={child.id}
                    text={String(child.event.payload.body ?? '')}
                  />
                ) : (
                  <div className="text-secondary">
                    <Prose>{String(child.event.payload.body ?? '')}</Prose>
                  </div>
                )
              ) : !child.event || child.event.type === 'tool.called' ? (
                <ToolCall ctx={ctx} entry={child} />
              ) : (
                <EntryBody ctx={ctx} entry={child} />
              )}
            </div>
          ))}
        </div>
      )}
    </Collapsible>
  )
}

/** Bring the `#e<seq>` row of the URL into view once the log has rows. */
function useScrollToHash(hash: string, ready: boolean) {
  useEffect(() => {
    if (!ready || !hash.startsWith('#e')) return
    document
      .getElementById(hash.slice(1))
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [hash, ready])
}
