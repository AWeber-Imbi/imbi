import { useCallback, useMemo, useRef, useState } from 'react'

import {
  ArrowRightToLine,
  ChartColumn,
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
import type { AgentTask, AgentTaskEvent } from '@/types'

import { ActivityEmpty, NoMatches } from './ActivityEmpty'
import {
  type ContextBasis,
  type StatsCells,
  type StatsStep,
  type StatsTurn,
  taskStatistics,
} from './statsModel'
import { Prose } from './taskEntryViews'
import { formatElapsed, formatTokens } from './taskEvents'
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
import { buildTrajectory, formatDuration } from './trajectoryModel'
import { useStoredState } from './useStoredState'
import { gapsOf, useVirtualRows } from './virtualRows'

const ANSWER_CAP = 16_000

interface Measure {
  'aria-rowindex': number
  'data-index': number
  ref: (row: HTMLElement | null) => void
}

type StatsRow =
  | { expanded: boolean; kind: 'turn'; steps: number; turn: StatsTurn }
  | { key: string; kind: 'answer'; step: StatsStep }
  | { key: string; kind: 'step'; max: number; shown: boolean; step: StatsStep }

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
      'A turn row holds the turn total. Click a turn to show or hide its steps, and a step to read its answer.',
    width: '11.5rem',
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
    label: 'Model',
    number: true,
    title: 'Model time: from the start of the step to the model’s reply.',
    width: '5rem',
  },
  {
    label: 'Tools',
    number: true,
    title: 'Tool time: every tool call in the step, added up.',
    width: '5rem',
  },
  {
    label: 'Speed',
    number: true,
    title: 'Output speed: output tokens ÷ model seconds.',
    width: '5.25rem',
  },
  {
    label: 'Total',
    title:
      'Total time. Purple is model time, amber is tool time, grey is everything else. Bar length uses a square-root scale: steps compare with steps of the same turn, turns with turns.',
    width: '8.5rem',
  },
]

export function StatisticsTab({
  events,
  onShowInConversation,
  task,
}: {
  events: AgentTaskEvent[]
  /** Opens the conversation at the turn that holds this event. */
  onShowInConversation?: (seq: number) => void
  task: AgentTask
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
  const [answers, setAnswers] = useState<Set<string>>(new Set())
  const [query, setQuery] = useTaskSearch()
  const root = useRef<HTMLDivElement>(null)
  useSearchHighlight(root, query)
  const searching = query.trim() !== ''
  const shown = useMemo(
    () =>
      searching
        ? stats.turns.flatMap((turn) => {
            const steps = turn.steps.filter((s) =>
              matches(`${s.did} ${s.answer}`, query),
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
            const row: StatsRow = {
              key,
              kind: 'step',
              max,
              shown: answers.has(key),
              step,
            }
            return answers.has(key)
              ? [row, { key: `${key}:answer`, kind: 'answer', step }]
              : [row]
          }),
        ]
      }),
    [answers, open, searching, shown],
  )
  const scroller = useRef<HTMLDivElement>(null)
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
    estimateSize: (i) => (flat[i]?.kind === 'answer' ? 160 : 37),
    getItemKey: keyOf,
    keep: [focusRow],
    scroller,
  })
  const { after, rows: rendered } = gapsOf(
    virtualizer.getVirtualItems(),
    virtualizer.getTotalSize(),
  )

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
          onToggle={
            row.step.answer
              ? () => setAnswers((s) => toggled(s, row.key))
              : undefined
          }
          shown={row.shown}
          step={row.step}
        />
      )
    return (
      <TableRow className="hover:bg-transparent" key={row.key} {...measure}>
        <TableCell
          className="bg-secondary py-3! pl-9!"
          colSpan={COLUMNS.length}
        >
          <Prose>{row.step.answer.slice(0, ANSWER_CAP)}</Prose>
          {row.step.answer.length > ANSWER_CAP && (
            <p className="text-tertiary mt-2 text-xs">
              The answer is cut off at {ANSWER_CAP.toLocaleString()} characters.
            </p>
          )}
        </TableCell>
      </TableRow>
    )
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
            >
              {rendered.flatMap(({ before, item }) => [
                ...(before > 0
                  ? [<Gap height={before} key={`gap-${item.key}`} />]
                  : []),
                renderRow(flat[item.index], item.index),
              ])}
              {after > 0 && <Gap height={after} />}
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
                </TableCell>
                <Numbers
                  cells={stats.totals}
                  speedTitle={
                    stats.totals.subrequests
                      ? 'Main-agent output tokens per second of model time. Subagent tokens count in Output but carry no model time.'
                      : undefined
                  }
                />
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

function clock(ms: null | number): string | undefined {
  if (ms === null) return undefined
  const d = new Date(ms)
  const pad = (n: number, w = 2) => String(n).padStart(w, '0')
  return `Started ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function Gap({ height }: { height: number }) {
  return (
    <tr aria-hidden style={{ height }}>
      <td className="p-0!" colSpan={COLUMNS.length} />
    </tr>
  )
}

function Numbers({
  cells,
  delta,
  speedTitle = 'Output tokens per second of model time',
}: {
  cells: StatsCells
  delta?: null | number
  speedTitle?: string
}) {
  const cell = 'truncate text-right tabular-nums'
  return (
    <>
      <TableCell className={cell}>
        {tokens(cells.context)}
        {delta !== undefined && delta !== null && delta !== 0 && (
          <span
            className={cn(
              'ml-1.5 text-xs',
              delta < 0 ? 'text-danger' : 'text-tertiary',
            )}
          >
            {delta > 0 ? '+' : '−'}
            {formatTokens(Math.abs(delta))}
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
      <TableCell className={cell}>{time(cells.modelMs)}</TableCell>
      <TableCell className={cell}>{time(cells.toolMs)}</TableCell>
      <TableCell
        className={cell}
        title={cells.outputPerSecond === null ? undefined : speedTitle}
      >
        {speed(cells.outputPerSecond)}
      </TableCell>
    </>
  )
}

function percent(share: null | number): string {
  return share === null ? '—' : `${Math.round(share * 100)}%`
}

function plural(n: number, one: string): string {
  return `${n} ${n === 1 ? one : `${one}s`}`
}

function speed(perSecond: null | number): string {
  if (perSecond === null) return '—'
  return `${perSecond < 10 ? perSecond.toFixed(1) : Math.round(perSecond)}/s`
}

function StepRow({
  delta,
  max,
  measure,
  onToggle,
  shown,
  step,
}: {
  delta: boolean
  max: number
  measure: Measure
  onToggle?: () => void
  shown: boolean
  step: StatsStep
}) {
  return (
    <TableRow
      className={cn('text-secondary', onToggle && 'cursor-pointer')}
      onClick={onToggle}
      {...measure}
    >
      <TableCell className="truncate pl-9!" title={clock(step.startedAt)}>
        {onToggle ? (
          <button
            aria-expanded={shown}
            aria-label={`Step ${step.number}: ${shown ? 'hide' : 'show'} its answer`}
            className="outline-none focus-visible:underline"
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
            type="button"
          >
            Step {step.number}
          </button>
        ) : (
          `Step ${step.number}`
        )}
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

function time(ms: null | number): string {
  if (ms === null) return '—'
  return ms < 60_000 ? formatDuration(ms) : formatElapsed(ms)
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
      <span className="w-12 text-right text-xs tabular-nums">
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
