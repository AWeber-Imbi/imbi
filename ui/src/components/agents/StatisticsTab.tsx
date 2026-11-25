import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  ArrowRightToLine,
  Bot,
  ChartColumn,
  ChartGantt,
  ChevronRight,
  Diff,
  MessageSquareText,
  Sigma,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { IconTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Ticket, TicketEvent } from '@/types'

import { ActivityEmpty, NoMatches } from './ActivityEmpty'
import { FindStub } from './FindStub'
import {
  type ContextBasis,
  type StatsCells,
  type StatsRanked,
  type StatsStep,
  type StatsSubagent,
  type StatsTurn,
  taskStatistics,
} from './statsModel'
import { money, StatsSummary, time } from './StatsSummary'
import { formatTokens } from './taskEvents'
import {
  matches,
  ToolbarSearch,
  useSearchHighlight,
  useTaskSearch,
} from './taskSearch'
import {
  TaskCopyMenu,
  TaskToolbar,
  ToolbarChoice,
  type ToolbarOption,
  ToolbarToggle,
} from './TaskToolbar'
import { buildTrajectory } from './trajectoryModel'
import { useStoredState } from './useStoredState'
import { gapsOf, scrollToFound, useVirtualRows } from './virtualRows'

interface Measure {
  'aria-rowindex': number
  'data-index': number
  ref: (row: HTMLElement | null) => void
}

type StatsRow =
  | { expanded: boolean; kind: 'turn'; steps: number; turn: StatsTurn }
  | { key: string; kind: 'step'; max: number; step: StatsStep }
  | { key: string; kind: 'subagent'; max: number; sub: StatsSubagent }

const BASES: ToolbarOption<ContextBasis>[] = [
  {
    hint: 'Latest: a turn shows the context of its last step',
    icon: ArrowRightToLine,
    label: 'Latest',
    value: 'latest',
  },
  {
    hint: 'Cumulative: a turn adds up the context of its steps',
    icon: Sigma,
    label: 'Cumulative',
    value: 'cumulative',
  },
]

const COLUMNS: {
  label: string
  number?: boolean
  title: string
  width?: string
}[] = [
  {
    label: 'Turn / step',
    title:
      'A turn row holds the turn total. Click a turn to show or hide its steps. Double-click a step or subagent to open it in the trajectory.',
    width: '14rem',
  },
  {
    label: 'Trigger / execution',
    title:
      'A turn shows what opened it: a person’s message, or the automation that started it. A step shows the tools it called, or its answer when it called none.',
  },
  {
    label: 'Context',
    number: true,
    title: 'Uncached input + cache read + cache write of the model request.',
    width: '6.5rem',
  },
  {
    label: 'Output',
    number: true,
    title: 'Output tokens of the model request.',
    width: '4.5rem',
  },
  {
    label: 'Cache',
    number: true,
    title: 'Cache read ÷ context: the share of the prompt served from cache.',
    width: '4.5rem',
  },
  {
    label: 'Cost',
    number: true,
    title:
      'Cost of the model requests. A turn and the task total include their subagents.',
    width: '4.75rem',
  },
  {
    label: 'Model',
    number: true,
    title:
      'Model time: from the start of the step to the model’s reply. Hover a cell for the output speed. A subagent reports no model time, so its cell shows its run time minus its tool time.',
    width: '5.75rem',
  },
  {
    label: 'Tools',
    number: true,
    title:
      'Tool time: how long any tool call of the step was running. Calls that ran at the same time count once.',
    width: '5rem',
  },
  {
    label: 'Total',
    title:
      'Total time. Purple is model time, amber is tool time, grey is everything else. A subagent’s purple is estimated. Bar length uses a square-root scale: steps compare with steps of the same turn, turns with turns.',
    width: '8.5rem',
  },
]

export function StatisticsTab({
  events,
  onShowInConversation,
  onShowInTrajectory,
  task,
}: {
  events: TicketEvent[]
  /** Opens the conversation at the turn that holds this event. */
  onShowInConversation?: (seq: number) => void
  /** Opens the trajectory at the row that holds this event. */
  onShowInTrajectory?: (seq: number) => void
  task: Ticket
}) {
  const [basis, setBasis] = useStoredState<ContextBasis>(
    'imbi.statistics.basis',
    'latest',
    (v) => (v === 'latest' || v === 'cumulative' ? v : undefined),
  )
  const [delta, setDelta] = useStoredState(
    'imbi.statistics.delta',
    false,
    (v) => (typeof v === 'boolean' ? v : undefined),
  )
  const live = task.status !== 'closed'
  const trajectory = useMemo(
    () => buildTrajectory(events, live),
    [events, live],
  )
  const stats = useMemo(
    () => taskStatistics(task, trajectory, basis),
    [task, trajectory, basis],
  )
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [seeded, setSeeded] = useState(false)
  if (!seeded && stats.turns.length) {
    setSeeded(true)
    if (stats.turns.length === 1) setOpen(new Set([stats.turns[0].number]))
  }
  const [query, setQuery] = useTaskSearch()
  const root = useRef<HTMLDivElement>(null)
  useSearchHighlight(root, query)
  const searching = query.trim() !== ''
  const shown = useMemo(
    () =>
      searching
        ? stats.turns.flatMap((turn) => {
            const steps = turn.steps.filter((s) =>
              matches(
                `${s.did} ${s.subagents.map((a) => `${a.description} ${a.type}`).join(' ')}`,
                query,
              ),
            )
            return steps.length || matches(turn.trigger.text, query)
              ? [{ steps: steps.length ? steps : turn.steps, turn }]
              : []
          })
        : stats.turns.map((turn) => ({ steps: turn.steps, turn })),
    [query, searching, stats.turns],
  )
  const maxTurn = Math.max(0, ...stats.turns.map((t) => t.totalMs ?? 0))
  const flat = useMemo(
    () =>
      shown.flatMap(({ steps, turn }): StatsRow[] => {
        const expanded = searching || open.has(turn.number)
        const head: StatsRow = {
          expanded,
          kind: 'turn',
          steps: steps.length,
          turn,
        }
        if (!expanded) return [head]
        const max = Math.max(0, ...turn.steps.map((s) => s.totalMs ?? 0))
        return [
          head,
          ...steps.flatMap((step): StatsRow[] => {
            const key = `${turn.number}:${step.number}`
            const row: StatsRow = { key, kind: 'step', max, step }
            const subs = step.subagents.map(
              (sub): StatsRow => ({
                key: `${key}:${sub.id}`,
                kind: 'subagent',
                max,
                sub,
              }),
            )
            return [row, ...subs]
          }),
        ]
      }),
    [open, searching, shown],
  )
  const scroller = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLTableSectionElement>(null)
  const [margin, setMargin] = useState(0)
  const laidOut = shown.length > 0
  useLayoutEffect(() => {
    const pane = scroller.current
    const rows = body.current
    if (!pane || !rows) return
    const measure = () =>
      setMargin(
        rows.getBoundingClientRect().top -
          pane.getBoundingClientRect().top +
          pane.scrollTop,
      )
    measure()
    const observer = new ResizeObserver(measure)
    for (const el of pane.querySelectorAll(':scope > :not(:last-child), thead'))
      observer.observe(el)
    return () => observer.disconnect()
  }, [laidOut, searching])
  const [reveal, setReveal] = useState<null | string>(null)
  const [selected, setSelected] = useState<null | string>(null)
  const [focusKey, setFocusKey] = useState<null | string>(null)
  const keyOf = useCallback(
    (i: number) => {
      const row = flat[i]
      return row.kind === 'turn' ? `turn:${row.turn.number}` : row.key
    },
    [flat],
  )
  const focusRow =
    focusKey === null ? -1 : flat.findIndex((_, i) => keyOf(i) === focusKey)
  const virtualizer = useVirtualRows({
    count: flat.length,
    estimateSize: () => 37,
    getItemKey: keyOf,
    keep: [focusRow],
    scroller,
    scrollMargin: margin,
  })
  const {
    after,
    afterSkipped,
    rows: rendered,
  } = gapsOf(
    virtualizer.getVirtualItems(),
    virtualizer.getTotalSize(),
    flat.length,
    margin,
  )
  const found = useCallback(
    (index: number) => scrollToFound(virtualizer, index),
    [virtualizer],
  )
  useEffect(() => {
    if (reveal === null) return
    const index = flat.findIndex((_, i) => keyOf(i) === reveal)
    if (index < 0) return
    found(index)
    setSelected(reveal)
    setReveal(null)
  }, [flat, found, keyOf, reveal])
  const onReveal = (item: StatsRanked) => {
    setQuery('')
    setOpen((s) => new Set(s).add(item.turn))
    setReveal(
      `${item.turn}:${item.step}${item.subagent ? `:${item.subagent}` : ''}`,
    )
  }
  const openIn = (seq: null | number) =>
    onShowInTrajectory && seq !== null
      ? () => onShowInTrajectory(seq)
      : undefined
  const stubs = (indexes: number[]) =>
    indexes.map((i) => (
      <FindStub
        index={i}
        key={keyOf(i)}
        onFound={found}
        text={findText(flat[i], delta)}
      />
    ))

  const renderRow = (row: StatsRow, index: number) => {
    const measure = {
      'aria-rowindex': index + 2,
      'data-index': index,
      ref: virtualizer.measureElement,
    }
    if (row.kind === 'turn') {
      const { seq } = row.turn
      return (
        <TurnRow
          delta={delta}
          expanded={row.expanded}
          key={`turn:${row.turn.number}`}
          max={maxTurn}
          measure={measure}
          onShow={
            onShowInConversation && seq !== null
              ? () => onShowInConversation(seq)
              : undefined
          }
          onToggle={
            searching
              ? undefined
              : () => setOpen((s) => toggled(s, row.turn.number))
          }
          shownSteps={row.steps}
          turn={row.turn}
        />
      )
    }
    if (row.kind === 'step')
      return (
        <StepRow
          delta={delta}
          key={row.key}
          max={row.max}
          measure={measure}
          onOpen={openIn(row.step.seq)}
          onSelect={() => setSelected(row.key)}
          selected={selected === row.key}
          step={row.step}
        />
      )
    if (row.kind === 'subagent')
      return (
        <SubagentRow
          key={row.key}
          max={row.max}
          measure={measure}
          onOpen={openIn(row.sub.seq)}
          onSelect={() => setSelected(row.key)}
          selected={selected === row.key}
          sub={row.sub}
        />
      )
    return null
  }

  return (
    <div
      className="trajectory isolate flex min-h-0 flex-1 flex-col overflow-hidden"
      ref={root}
    >
      <TaskToolbar label="Statistics">
        <ToolbarChoice
          label="Context basis"
          onChange={setBasis}
          options={BASES}
          value={basis}
        />
        <ToolbarToggle
          hint="Show the change in context from the previous step or turn. A drop shows in red."
          icon={Diff}
          label="Show context change"
          onPressedChange={setDelta}
          pressed={delta}
        />
        <div className="ml-auto flex min-w-40 flex-1 items-center justify-end gap-2">
          <ToolbarSearch
            label="Search statistics"
            onChange={setQuery}
            value={query}
          />
          <TaskCopyMenu events={events} task={task} />
        </div>
      </TaskToolbar>
      {stats.turns.length === 0 ? (
        <ActivityEmpty icon={<ChartColumn />} title="No activity yet">
          No model requests yet.
        </ActivityEmpty>
      ) : shown.length === 0 ? (
        <NoMatches onClear={() => setQuery('')} query={query} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto" ref={scroller}>
          {!searching && <StatsSummary onReveal={onReveal} stats={stats} />}
          <Table
            aria-rowcount={flat.length + 2}
            className="min-w-264 table-fixed text-sm [&_td]:px-2.5 [&_td]:py-1.5 [&_th]:px-2.5"
          >
            <colgroup>
              {COLUMNS.map((c) => (
                <col
                  key={c.label}
                  style={c.width ? { width: c.width } : undefined}
                />
              ))}
            </colgroup>
            <TableHeader className="bg-tertiary sticky top-0 z-1">
              <TableRow aria-rowindex={1}>
                {COLUMNS.map((c) => (
                  <TableHead
                    className={cn(
                      'h-9 truncate text-xs text-secondary',
                      c.number && 'text-right',
                    )}
                    key={c.label}
                    title={c.title}
                  >
                    {c.label}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody
              onFocus={(e) => {
                const index = (e.target as HTMLElement).closest<HTMLElement>(
                  '[data-index]',
                )?.dataset.index
                if (index !== undefined) setFocusKey(keyOf(Number(index)))
              }}
              ref={body}
            >
              {rendered.flatMap(({ before, item, skipped }) => [
                ...(before > 0 || skipped.length
                  ? [
                      <Gap height={before} key={`gap-${item.key}`}>
                        {stubs(skipped)}
                      </Gap>,
                    ]
                  : []),
                renderRow(flat[item.index], item.index),
              ])}
              {(after > 0 || afterSkipped.length > 0) && (
                <Gap height={after}>{stubs(afterSkipped)}</Gap>
              )}
            </TableBody>
            <TableFooter className="bg-secondary sticky bottom-0">
              <TableRow
                aria-rowindex={flat.length + 2}
                className="hover:bg-transparent"
              >
                <TableCell
                  className="truncate font-medium"
                  title="Totals for the whole task, subagent tokens included. Total time adds up the time of each turn, without the gaps between turns."
                >
                  Task total
                </TableCell>
                <TableCell className="text-secondary truncate">
                  {plural(stats.totals.turns, 'turn')} ·{' '}
                  {plural(stats.totals.steps, 'step')}
                  {stats.totals.subagents > 0 &&
                    ` · ${plural(stats.totals.subagents, 'subagent')}`}
                </TableCell>
                <Numbers cells={stats.totals} />
                <TableCell className="truncate text-right tabular-nums">
                  {time(stats.totals.totalMs)}
                </TableCell>
              </TableRow>
            </TableFooter>
          </Table>
        </div>
      )}
    </div>
  )
}

/** The context change a cell shows beside the context, if any. */
function changeText(delta?: null | number): string {
  if (delta === undefined || delta === null || delta === 0) return ''
  return `${delta > 0 ? '+' : '−'}${formatTokens(Math.abs(delta))}`
}

function clock(ms: null | number): string | undefined {
  if (ms === null) return undefined
  const d = new Date(ms)
  const pad = (n: number, w = 2) => String(n).padStart(w, '0')
  return `Started ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

/** The text of a row as it renders, for the browser's find. */
function findText(row: StatsRow, delta: boolean): string {
  if (row.kind === 'turn')
    return `Turn ${row.turn.number} ${row.turn.trigger.text} ${numbersText(row.turn, delta)}`
  if (row.kind === 'step')
    return `Step ${row.step.number} ${row.step.did} ${numbersText(row.step, delta)}`
  return `${row.sub.description} ${subagentText(row.sub)} ${numbersText({ ...row.sub, contextDelta: null }, false)}`
}

function Gap({ children, height }: { children?: ReactNode; height: number }) {
  return (
    <tr aria-hidden style={{ height }}>
      <td className="p-0! align-top" colSpan={COLUMNS.length}>
        {children}
      </td>
    </tr>
  )
}

function Numbers({
  cells,
  delta,
}: {
  cells: StatsCells
  delta?: null | number
}) {
  const cell = 'truncate text-right tabular-nums'
  const change = changeText(delta)
  return (
    <>
      <TableCell className={cell}>
        {tokens(cells.context)}
        {change && (
          <span
            className={cn(
              'ml-1.5 text-xs',
              (delta ?? 0) < 0 ? 'text-danger' : 'text-tertiary',
            )}
          >
            {change}
          </span>
        )}
      </TableCell>
      <TableCell className={cell}>{tokens(cells.output)}</TableCell>
      <TableCell
        className={cell}
        title={`Cache read ${formatTokens(cells.cacheRead)} · uncached input ${formatTokens(cells.input)} · cache write ${formatTokens(cells.cacheWrite)}`}
      >
        {percent(cells.cacheHit)}
      </TableCell>
      <TableCell className={cell}>{money(cells.cost)}</TableCell>
      <TableCell className={cell} title={speedText(cells.outputPerSecond)}>
        {time(cells.modelMs)}
      </TableCell>
      <TableCell className={cell}>{time(cells.toolMs)}</TableCell>
    </>
  )
}

/** The numbers a row's cells show, as they show them. */
function numbersText(
  cells: StatsCells & { contextDelta: null | number },
  delta: boolean,
): string {
  return [
    `${tokens(cells.context)}${changeText(delta ? cells.contextDelta : undefined)}`,
    tokens(cells.output),
    percent(cells.cacheHit),
    money(cells.cost),
    time(cells.modelMs),
    time(cells.toolMs),
    time(cells.totalMs),
  ].join(' ')
}

function OpenInTrajectory({
  label,
  onOpen,
}: {
  label: string
  onOpen?: () => void
}) {
  if (!onOpen) return null
  return (
    <IconTooltip label="Open in trajectory">
      <Button
        aria-label={`${label}: open in trajectory`}
        className="text-tertiary hover:text-primary -my-1 size-6 shrink-0 opacity-0 group-hover/row:opacity-100 group-data-selected/row:opacity-100 focus-visible:opacity-100 [&_svg]:size-3.5"
        onClick={(e) => {
          e.stopPropagation()
          onOpen()
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        size="icon"
        variant="ghost"
      >
        <ChartGantt />
      </Button>
    </IconTooltip>
  )
}

function percent(share: null | number): string {
  return share === null ? '—' : `${Math.round(share * 100)}%`
}

function plural(n: number, one: string): string {
  return `${n} ${n === 1 ? one : `${one}s`}`
}

function speedText(perSecond: null | number): string | undefined {
  if (perSecond === null) return undefined
  const n = perSecond < 10 ? perSecond.toFixed(1) : Math.round(perSecond)
  return `${n} output tokens per second`
}

function StepRow({
  delta,
  max,
  measure,
  onOpen,
  onSelect,
  selected,
  step,
}: {
  delta: boolean
  max: number
  measure: Measure
  onOpen?: () => void
  onSelect: () => void
  selected: boolean
  step: StatsStep
}) {
  return (
    <TableRow
      className={cn(
        'group/row cursor-pointer text-secondary',
        selected &&
          'bg-action/10 inset-ring inset-ring-action/35 hover:bg-action/10',
      )}
      data-selected={selected || undefined}
      onClick={onSelect}
      onDoubleClick={onOpen}
      {...measure}
    >
      <TableCell className="pl-9!" title={clock(step.startedAt)}>
        <span className="flex min-w-0 items-center justify-between gap-1">
          <span className="truncate">Step {step.number}</span>
          <OpenInTrajectory label={`Step ${step.number}`} onOpen={onOpen} />
        </span>
      </TableCell>
      <TableCell>
        <span className="block truncate" title={step.did}>
          {step.did || '—'}
        </span>
      </TableCell>
      <Numbers cells={step} delta={delta ? step.contextDelta : undefined} />
      <TableCell>
        <TimeBar cells={step} max={max} />
      </TableCell>
    </TableRow>
  )
}

function SubagentRow({
  max,
  measure,
  onOpen,
  onSelect,
  selected,
  sub,
}: {
  max: number
  measure: Measure
  onOpen?: () => void
  onSelect: () => void
  selected: boolean
  sub: StatsSubagent
}) {
  const cell = 'truncate text-right tabular-nums'
  const none = <span className="text-tertiary">—</span>
  return (
    <TableRow
      className={cn(
        'group/row cursor-pointer text-secondary',
        selected &&
          'bg-action/10 inset-ring inset-ring-action/35 hover:bg-action/10',
      )}
      data-selected={selected || undefined}
      onClick={onSelect}
      onDoubleClick={onOpen}
      {...measure}
    >
      <TableCell className="pl-14!" title={clock(sub.startedAt)}>
        <span className="flex min-w-0 items-center gap-1.5">
          <Bot className="text-tertiary size-3.5 shrink-0" />
          <span className="flex-1 truncate" title={sub.description}>
            {sub.description}
          </span>
          <OpenInTrajectory label={sub.description} onOpen={onOpen} />
        </span>
      </TableCell>
      <TableCell>
        <span className="block truncate" title={subagentText(sub)}>
          {sub.type && (
            <span className="text-tertiary mr-1.5 font-mono text-xs">
              {sub.type}
            </span>
          )}
          {subagentText(sub)}
        </span>
      </TableCell>
      <TableCell
        className={cell}
        title={`The prompt of the subagent’s last request. It made ${plural(sub.requests, 'model request')}.`}
      >
        {tokens(sub.context)}
      </TableCell>
      <TableCell className={cell}>{tokens(sub.output)}</TableCell>
      <TableCell
        className={cell}
        title={`Cache read ${formatTokens(sub.cacheRead)} · uncached input ${formatTokens(sub.input)} · cache write ${formatTokens(sub.cacheWrite)}`}
      >
        {percent(sub.cacheHit)}
      </TableCell>
      <TableCell className={cell}>{money(sub.cost)}</TableCell>
      <TableCell
        className={cell}
        title="Estimated: the subagent’s run time minus its tool time"
      >
        {sub.modelMs ? `≈${time(sub.modelMs)}` : none}
      </TableCell>
      <TableCell className={cell}>{time(sub.toolMs)}</TableCell>
      <TableCell>
        <TimeBar cells={sub} max={max} />
      </TableCell>
    </TableRow>
  )
}

function subagentText(sub: StatsSubagent): string {
  return [
    plural(sub.tools, 'tool'),
    plural(sub.requests, 'request'),
    sub.errors > 0 && `${sub.errors} failed`,
  ]
    .filter(Boolean)
    .join(' · ')
}

function TimeBar({ cells, max }: { cells: StatsCells; max: number }) {
  const total = cells.totalMs
  if (total === null || total <= 0 || max <= 0)
    return <span className="text-tertiary">—</span>
  const width = Math.max(4, (Math.sqrt(total) / Math.sqrt(max)) * 100)
  const model = Math.min(1, cells.modelMs / total)
  const tool = Math.min(1 - model, cells.toolMs / total)
  return (
    <div
      className="flex min-w-28 items-center gap-2"
      title={`Model ${time(cells.modelMs)} · tools ${time(cells.toolMs)} · total ${time(total)}`}
    >
      <div className="h-2 flex-1">
        <div
          className="flex h-full overflow-hidden rounded-sm bg-(--tj-border-2)"
          style={{ width: `${width}%` }}
        >
          <div
            className="h-full bg-(--tj-span-assistant)"
            style={{ width: `${model * 100}%` }}
          />
          <div
            className="h-full bg-(--tj-span-tool)"
            style={{ width: `${tool * 100}%` }}
          />
        </div>
      </div>
      <span className="w-12 shrink-0 text-right text-xs whitespace-nowrap tabular-nums">
        {time(total)}
      </span>
    </div>
  )
}

function toggled<T>(set: Set<T>, key: T): Set<T> {
  const next = new Set(set)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}

function tokens(n: null | number): string {
  return n === null ? '—' : formatTokens(n)
}

function TurnRow({
  delta,
  expanded,
  max,
  measure,
  onShow,
  onToggle,
  shownSteps,
  turn,
}: {
  delta: boolean
  expanded: boolean
  max: number
  measure: Measure
  onShow?: () => void
  onToggle?: () => void
  shownSteps: number
  turn: StatsTurn
}) {
  const count = plural(turn.steps.length, 'step')
  return (
    <TableRow
      className={cn('font-medium', onToggle && 'cursor-pointer')}
      onClick={onToggle}
      {...measure}
    >
      <TableCell>
        <div className="flex min-w-0 items-center gap-1">
          <button
            aria-expanded={expanded}
            aria-label={
              onToggle
                ? `Turn ${turn.number}: ${expanded ? 'hide' : 'show'} its ${count}`
                : `Turn ${turn.number}: its ${count}, open while searching`
            }
            className="flex min-w-0 items-center gap-1 outline-none focus-visible:underline disabled:cursor-default"
            disabled={!onToggle}
            onClick={(e) => {
              e.stopPropagation()
              onToggle?.()
            }}
            type="button"
          >
            <ChevronRight
              className={cn(
                'size-3.5 shrink-0 text-tertiary transition-transform',
                expanded && 'rotate-90',
              )}
            />
            <span className="truncate">
              Turn {turn.number}{' '}
              <span className="text-tertiary font-normal">
                ·{' '}
                {shownSteps < turn.steps.length
                  ? `${shownSteps} of ${count}`
                  : count}
              </span>
            </span>
          </button>
          {onShow && (
            <IconTooltip label="Show in conversation">
              <Button
                aria-label={`Turn ${turn.number}: show in conversation`}
                className="text-tertiary hover:text-primary size-6 shrink-0"
                onClick={(e) => {
                  e.stopPropagation()
                  onShow()
                }}
                size="icon"
                variant="ghost"
              >
                <MessageSquareText className="size-3.5" />
              </Button>
            </IconTooltip>
          )}
        </div>
      </TableCell>
      <TableCell className="font-normal">
        {turn.trigger.badge ? (
          <Badge
            className="max-w-full"
            title={turn.trigger.text}
            variant="info"
          >
            <span className="truncate">{turn.trigger.text}</span>
          </Badge>
        ) : (
          <span className="block truncate" title={turn.trigger.text}>
            {turn.trigger.text}
          </span>
        )}
      </TableCell>
      <Numbers cells={turn} delta={delta ? turn.contextDelta : undefined} />
      <TableCell>
        <TimeBar cells={turn} max={max} />
      </TableCell>
    </TableRow>
  )
}
