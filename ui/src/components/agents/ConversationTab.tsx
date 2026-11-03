import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { ChevronRight, Search, TriangleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { RichMarkdown } from '@/components/ui/rich-markdown'
import { UserIdentity } from '@/components/ui/user-identity'
import { cn } from '@/lib/utils'
import type { AgentTask, AgentTaskEvent } from '@/types'

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

/** The filter chips, in order. */
type ChipKey = 'messages' | 'subagents' | 'system' | 'thinking' | 'tools'

type Family = 'agent' | 'edit' | 'mcp' | 'read' | 'shell'

interface OutputProps {
  dark?: boolean
  error?: boolean
  text: string
}

interface RowContext {
  isOpen: (id: string) => boolean
  orgSlug: string
  requests: TaskRequestView[]
  task: AgentTask
  toggle: (id: string) => void
}

/** The tag colors of each tool family. */
const FAMILY_TAG: Record<Family, string> = {
  agent: 'bg-accent text-accent',
  edit: 'bg-teal text-teal',
  mcp: 'bg-accent text-accent',
  read: 'bg-info text-info',
  shell: 'bg-secondary text-primary',
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
/** Lines of output shown before "Show all". */
const OUTPUT_LINES = 40

/**
 * The task log as one timeline (O5): turns, tool calls, requests, and
 * state changes in order, with subagent work nested under its call,
 * filters by kind, and a compact or full level of detail.
 */
export function ConversationTab({
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
    task,
    toggle,
  }

  useScrollToHash(shown.length > 0)

  return (
    <div className="bg-tertiary flex min-h-full flex-col">
      <div className="border-tertiary bg-primary sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b px-6 py-2.5">
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
        <Segmented
          label="Detail"
          onChange={(v) => setDensity(v === 'Full')}
          options={['Compact', 'Full']}
          value={full ? 'Full' : 'Compact'}
        />
        <label className="border-secondary ml-auto flex items-center gap-1.5 rounded-md border px-2 py-1">
          <Search className="text-tertiary size-3.5" />
          <input
            aria-label="Search this task"
            className="w-40 bg-transparent text-xs outline-none"
            onChange={(e) => setFilters({ ...filters, query: e.target.value })}
            placeholder="Search this task"
            type="search"
            value={filters.query}
          />
        </label>
      </div>
      <ol className="flex-1 py-4">
        {all.length === 0 && (
          <li className="text-tertiary px-6 py-4 text-sm">
            No conversation yet.
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
  )
}

/** `Bash`, `Edit`, `github · get_pr`, `Subagent`. */
export function toolLabel(tool: string): string {
  if (tool.startsWith('mcp__')) {
    const [, server, ...name] = tool.split('__')
    return `${server} · ${name.join('__')}`
  }
  if (tool === 'Task' || tool === 'Agent') return 'Subagent'
  return tool
}

/** The one-line summary of a call's arguments. */
export function toolSummary(tool: string, args: unknown): string {
  const a = (args ?? {}) as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  switch (tool) {
    case 'Agent':
    case 'Task':
      return [str(a.subagent_type), str(a.description)]
        .filter(Boolean)
        .join(' · ')
    case 'Bash':
      return str(a.command)
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
    case 'Read':
    case 'Write':
      return str(a.file_path) || str(a.notebook_path)
    case 'Glob':
    case 'Grep':
      return [str(a.pattern), str(a.path)].filter(Boolean).join('  in ')
    case 'WebFetch':
      return str(a.url)
    case 'WebSearch':
      return str(a.query)
  }
  const first = Object.values(a).find((v) => typeof v === 'string')
  return typeof first === 'string' ? first : JSON.stringify(a)
}

function AgentMessage({ body, name }: { body: string; name: string }) {
  return (
    <div className="border-tertiary bg-primary flex flex-col gap-2 rounded-lg border px-4 pt-3 pb-3.5 shadow-xs">
      <div className="flex items-center gap-2">
        <span className="bg-action text-action-foreground grid size-5 place-items-center rounded-full text-[10px] font-semibold">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="text-sm font-semibold">{name}</span>
        <Badge variant="neutral">Agent</Badge>
      </div>
      <Prose>{body}</Prose>
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
            ? 'bg-danger text-danger border-transparent'
            : 'bg-secondary text-primary border-transparent'
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

/** Old text above new text, for an Edit, MultiEdit, or Write. */
function Diff({ args }: { args: Record<string, unknown> }) {
  const edits: { new_string?: unknown; old_string?: unknown }[] = Array.isArray(
    args.edits,
  )
    ? (args.edits as { new_string?: unknown; old_string?: unknown }[])
    : [
        {
          new_string: args.new_string ?? args.content,
          old_string: args.old_string,
        },
      ]
  const lines = (v: unknown) => (typeof v === 'string' ? v.split('\n') : [])
  return (
    <div className="border-tertiary overflow-x-auto rounded-md border">
      <div className="bg-secondary text-secondary px-3 py-1.5 font-mono text-xs">
        {String(args.file_path ?? '')}
      </div>
      <pre className="py-1 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {edits.map((edit, i) => (
          <span key={i}>
            {i > 0 && <span className="text-tertiary block px-3">⋯</span>}
            {lines(edit.old_string).map((l, j) => (
              <span className="bg-danger text-danger block px-3" key={`o${j}`}>
                - {l}
              </span>
            ))}
            {lines(edit.new_string).map((l, j) => (
              <span
                className="bg-success text-success block px-3"
                key={`n${j}`}
              >
                + {l}
              </span>
            ))}
          </span>
        ))}
      </pre>
    </div>
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

function familyOf(tool: string): Family {
  if (tool === 'Bash') return 'shell'
  if (['Edit', 'MultiEdit', 'NotebookEdit', 'Write'].includes(tool))
    return 'edit'
  if (tool === 'Task' || tool === 'Agent') return 'agent'
  if (tool.startsWith('mcp__')) return 'mcp'
  return 'read'
}

function HumanMessage({
  body,
  event,
}: {
  body: string
  event: AgentTaskEvent
}) {
  return (
    <div className="border-info/40 bg-info flex flex-col gap-2 rounded-lg border px-4 pt-3 pb-3.5">
      <div className="flex items-center gap-2">
        <UserIdentity email={event.actor_id ?? ''} size="small" />
        <Badge variant="info">Person</Badge>
        {!['harness', 'web'].includes(event.channel) && (
          <span className="text-tertiary text-xs">via {event.channel}</span>
        )}
      </div>
      <Prose>{body}</Prose>
      {typeof event.payload.decision === 'string' && (
        <p className="text-secondary text-sm">{event.payload.decision}</p>
      )}
    </div>
  )
}

/** A string as is; anything else as JSON. */
function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** Output text, cut at {@link OUTPUT_LINES} until the reader asks. */
function Output({ dark, error, text }: OutputProps) {
  const [all, setAll] = useState(false)
  const lines = text.split('\n')
  const cut = !all && lines.length > OUTPUT_LINES
  return (
    <>
      <Pane dark={dark}>
        <span
          className={cn(error && (dark ? 'text-[#f29a8e]' : 'text-danger'))}
        >
          {cut ? lines.slice(0, OUTPUT_LINES).join('\n') : text}
        </span>
      </Pane>
      {cut && (
        <button
          className="text-info self-start text-xs hover:underline"
          onClick={() => setAll(true)}
          type="button"
        >
          Show all {lines.length} lines
        </button>
      )}
    </>
  )
}

function Pane({ children, dark }: { children: ReactNode; dark?: boolean }) {
  return (
    <div
      className={cn(
        'overflow-x-auto rounded-md',
        dark ? 'bg-[#1f1f1d]' : 'border-tertiary bg-tertiary border',
      )}
    >
      <pre
        className={cn(
          'px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap',
          dark && 'text-[#e6e5df]',
        )}
      >
        {children}
      </pre>
    </div>
  )
}

function Prose({ children }: { children: string }) {
  return (
    <div className="document-markdown max-w-[74ch] text-sm">
      <RichMarkdown>{children}</RichMarkdown>
    </div>
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
  const small = categoryOf(entry) === 'system'
  return (
    <li
      className="grid grid-cols-[4.5rem_1.5rem_minmax(0,1fr)] pr-6 pl-2"
      id={e ? `e${e.seq}` : undefined}
    >
      <a
        className="text-tertiary hover:text-info pt-3 pr-1.5 text-right font-mono text-[11px] tabular-nums"
        href={e ? `#e${e.seq}` : undefined}
        title="Link to this event"
      >
        {e ? clock(e.at) : ''}
      </a>
      <div className="relative">
        <span
          className={cn(
            'absolute left-[11px] w-0.5 bg-(--ds-border-tertiary)',
            first ? 'top-4' : 'top-0',
            last ? 'h-4' : 'bottom-0',
          )}
        />
        <span
          className={cn(
            'absolute rounded-full bg-current ring-3 ring-(--ds-bg-tertiary)',
            small ? 'top-[11px] left-2 size-2' : 'top-[13px] left-1.5 size-3',
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

function Segmented({
  label,
  onChange,
  options,
  value,
}: {
  label: string
  onChange: (value: string) => void
  options: string[]
  value: string
}) {
  return (
    <span
      aria-label={label}
      className="border-secondary inline-flex overflow-hidden rounded-md border"
      role="group"
    >
      {options.map((option) => (
        <button
          aria-pressed={value === option}
          className={cn(
            'px-2.5 py-0.5 text-xs',
            value === option
              ? 'bg-secondary text-primary font-medium'
              : 'text-tertiary',
          )}
          key={option}
          onClick={() => onChange(option)}
          type="button"
        >
          {option}
        </button>
      ))}
    </span>
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
    <div className="border-amber-border/50 bg-amber-bg/50 rounded-lg border">
      <button
        aria-expanded={open}
        className="text-amber-text flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs"
        onClick={() => ctx.toggle(id)}
        type="button"
      >
        <ChevronRight
          className={cn('size-3.5 transition-transform', open && 'rotate-90')}
        />
        <span className="font-semibold">Thinking</span>
        <span className="text-tertiary">
          {text.split(/\s+/).filter(Boolean).length} words
        </span>
      </button>
      {open && (
        <p className="text-secondary max-w-[80ch] px-4 pb-3 pl-8 text-[13px] leading-relaxed whitespace-pre-wrap italic">
          {text}
        </p>
      )}
    </div>
  )
}

function Todos({ event }: { event: AgentTaskEvent }) {
  const todos = (event.payload.todos ?? []) as {
    done?: boolean
    title?: string
  }[]
  return (
    <div className="border-tertiary bg-primary inline-flex flex-col gap-1 rounded-lg border px-3 py-2">
      <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
        Plan · {todos.filter((t) => t.done).length} of {todos.length} done
      </span>
      <ul className="flex flex-col gap-0.5 text-xs">
        {todos.map((t, i) => (
          <li className={cn(t.done && 'text-tertiary line-through')} key={i}>
            <span
              className={cn(
                'inline-block w-4',
                t.done ? 'text-success' : 'text-tertiary',
              )}
            >
              {t.done ? '✓' : '○'}
            </span>
            {t.title}
          </li>
        ))}
      </ul>
    </div>
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
  const args = (p.arguments ?? {}) as Record<string, unknown>
  const ms = typeof p.duration_ms === 'number' ? p.duration_ms : null
  const denied = isDenied(p)
  const result = p.result == null ? '' : label(p.result)
  return (
    <div
      className={cn(
        'bg-primary overflow-hidden rounded-lg border shadow-xs',
        isError(entry) ? 'border-danger' : 'border-tertiary',
      )}
    >
      <button
        aria-expanded={e ? open : undefined}
        className="hover:bg-tertiary flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm"
        disabled={!e}
        onClick={() => ctx.toggle(entry.id)}
        type="button"
      >
        <ChevronRight
          className={cn(
            'text-tertiary size-3.5 shrink-0 transition-transform',
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
          {e ? toolSummary(tool, args) : 'Running…'}
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
      </button>
      {open && e && (
        <div className="border-tertiary flex flex-col gap-2 border-t px-3 pt-2.5 pb-3">
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
            <span className="ml-auto">
              <Segmented
                label="View"
                onChange={(v) => setJson(v === 'JSON')}
                options={['Readable', 'JSON']}
                value={json ? 'JSON' : 'Readable'}
              />
            </span>
          </div>
          {json ? (
            <Pane>{JSON.stringify(p, null, 2)}</Pane>
          ) : (
            <ToolReadable
              args={args}
              error={p.is_error === true}
              family={family}
              result={result}
            />
          )}
        </div>
      )}
      {entry.children.length > 0 && (
        <div className="border-accent/40 mx-3 mb-3 ml-6 flex flex-col gap-2 border-l-2 pt-1 pl-3.5">
          <span className="text-accent text-[10.5px] font-semibold tracking-wide uppercase">
            {String(args.subagent_type ?? 'Subagent')}
          </span>
          {entry.children.map((child) =>
            child.event?.type === 'turn' ? (
              child.event.payload.kind === 'thinking' ? (
                <Thinking
                  ctx={ctx}
                  id={child.id}
                  key={child.id}
                  text={String(child.event.payload.body ?? '')}
                />
              ) : (
                <div className="text-secondary" key={child.id}>
                  <Prose>{String(child.event.payload.body ?? '')}</Prose>
                </div>
              )
            ) : (
              <ToolCall ctx={ctx} entry={child} key={child.id} />
            ),
          )}
        </div>
      )}
    </div>
  )
}

function ToolReadable({
  args,
  error,
  family,
  result,
}: {
  args: Record<string, unknown>
  error: boolean
  family: Family
  result: string
}) {
  if (family === 'shell')
    return (
      <Output
        dark
        error={error}
        text={`$ ${String(args.command ?? '')}${result ? `\n${result}` : ''}`}
      />
    )
  if (family === 'edit' && !error) return <Diff args={args} />
  return (
    <>
      <Pane>
        {Object.entries(args).map(([k, v], i) => (
          <span key={k}>
            {i > 0 && '\n'}
            <span className="text-tertiary">{k}</span> {label(v)}
          </span>
        ))}
      </Pane>
      {result && (
        <>
          <span className="text-tertiary text-[10.5px] font-semibold tracking-wide uppercase">
            Output
          </span>
          <Output error={error} text={result} />
        </>
      )}
    </>
  )
}

/** Scroll to the `#e<seq>` of the URL once the timeline has rows. */
function useScrollToHash(ready: boolean) {
  useEffect(() => {
    if (!ready || !window.location.hash.startsWith('#e')) return
    document
      .getElementById(window.location.hash.slice(1))
      ?.scrollIntoView?.({ block: 'center' })
  }, [ready])
}
