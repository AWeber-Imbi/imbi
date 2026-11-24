import {
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'

import { Info, Settings, Sparkle, User, Wrench } from 'lucide-react'

import { clockTime, fullTime } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

import { FindStub } from './FindStub'
import {
  type Fold,
  KIND_LABEL,
  type TrajectoryKind,
  type TrajectoryRecord,
  type TrajectoryRequest,
  type TrajectoryRow,
} from './trajectoryModel'
import { sameWindow, type TrajectoryWindow, windowOf } from './trajectoryWindow'
import { gapsOf, scrollToFound, unlaidOf, useVirtualRows } from './virtualRows'

export type TrajectorySelection =
  | null
  | { assistant: string; type: 'request' }
  | { id: string; type: 'record' }

const TAG: Record<TrajectoryKind, string> = {
  assistant: 'justify-center bg-(--tj-assistant-bg) text-(--tj-assistant)',
  context: 'bg-(--tj-success-3) text-(--tj-context)',
  subtool: 'bg-(--tj-subtool-bg) text-(--tj-subtool)',
  system: 'bg-(--tj-bg-module) text-(--tj-label-2)',
  tool: 'bg-(--tj-warn-3) text-(--tj-warn)',
  user: 'bg-(--tj-business-3) text-(--tj-business)',
}

const MOVES: Record<string, (i: number, last: number) => number> = {
  ArrowDown: (i) => i + 1,
  ArrowUp: (i) => i - 1,
  End: (_, last) => last,
  Home: () => 0,
}

const ICON = {
  assistant: Sparkle,
  context: Info,
  subtool: Wrench,
  system: Settings,
  tool: Wrench,
  user: User,
}

interface LedgerProps {
  activeTurn: null | number
  /** Record ids inside the overview range; null when there is no range. */
  focused: null | Set<string>
  onClear: () => void
  onDoubleClick: (record: TrajectoryRecord) => void
  onFold: (fold: Fold) => void
  onSelect: (selection: TrajectorySelection) => void
  /** Called with the record rows in view as they change. */
  onVisible?: (visible: null | TrajectoryWindow) => void
  requests: TrajectoryRequest[]
  rows: TrajectoryRow[]
  /** A new object scrolls the ledger to that record. */
  scrollTo: null | { id: string }
  selection: TrajectorySelection
  /** The turn number at the row where each turn starts. */
  turnStarts: Map<string, number>
}

/** The kind tag of a record: a label, or an icon when the table is narrow. */
export function KindTag({
  className,
  kind,
}: {
  className?: string
  kind: TrajectoryKind
}) {
  const Icon = ICON[kind]
  return (
    <span
      className={cn(
        'inline-flex h-5 shrink-0 items-center rounded-[4px] px-1.5 text-[11px] leading-4 font-[650] tracking-[.035em] uppercase @max-[620px]/tj:w-5 @max-[620px]/tj:justify-center @max-[620px]/tj:px-0',
        TAG[kind],
        className,
      )}
    >
      <span className="@max-[620px]/tj:hidden">{KIND_LABEL[kind]}</span>
      <Icon
        aria-hidden
        className="hidden size-3.25 @max-[620px]/tj:block"
        strokeWidth={1.75}
      />
    </span>
  )
}

/**
 * The ledger: one row per record, an event column with its kind tag and
 * a content column, plus summary rows for folds.
 */
export function TrajectoryLedger({
  activeTurn,
  focused,
  onClear,
  onDoubleClick,
  onFold,
  onSelect,
  onVisible,
  requests,
  rows,
  scrollTo,
  selection,
  turnStarts,
}: LedgerProps) {
  const pane = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const requestAt = new Map(requests.map((r) => [r.assistant, r]))
  const shown = useRef<null | TrajectoryWindow>(null)
  const [focusKey, setFocusKey] = useState<null | string>(null)
  const moving = useRef<null | number>(null)
  const scrolled = useRef<LedgerProps['scrollTo']>(null)
  const centred = useRef('')

  const selectedRow = rows.findIndex(
    (row) =>
      row.kind === 'record' &&
      ((selection?.type === 'record' && selection.id === row.record.id) ||
        (selection?.type === 'request' &&
          selection.assistant === row.record.id)),
  )
  const keyOf = useCallback(
    (i: number) => {
      const row = rows[i]
      return row.kind === 'summary' ? row.id : row.record.id
    },
    [rows],
  )
  const focusRow =
    focusKey === null ? -1 : rows.findIndex((_, i) => keyOf(i) === focusKey)
  const report = (v: typeof virtualizer) => {
    if (!onVisible) return
    const top = v.scrollOffset ?? 0
    const next = unlaidOf(v)
      ? null
      : windowOf(
          v.getVirtualItems().flatMap((item) => {
            const row = rows[item.index]
            return row?.kind === 'record'
              ? [{ bottom: item.end, id: row.record.id, top: item.start }]
              : []
          }),
          top,
          top + (v.scrollRect?.height ?? 0),
        )
    if (sameWindow(shown.current, next)) return
    shown.current = next
    onVisible(next)
  }
  const virtualizer = useVirtualRows({
    count: rows.length,
    estimateSize: (i) => (rows[i]?.kind === 'summary' ? 24 : 36),
    getItemKey: keyOf,
    keep: [selectedRow, focusRow],
    onChange: report,
    scroller: pane,
  })
  const items = virtualizer.getVirtualItems()

  useLayoutEffect(() => {
    const el = pane.current
    if (el && following.current) el.scrollTop = el.scrollHeight
  }, [rows.length])

  useEffect(() => {
    report(virtualizer)
  })

  useEffect(() => {
    if (!scrollTo || scrolled.current === scrollTo) return
    const index = rows.findIndex(
      (row) => row.kind === 'record' && row.record.id === scrollTo.id,
    )
    if (index < 0) return
    scrolled.current = scrollTo
    virtualizer.scrollToIndex(index, { align: 'auto' })
  }, [rows, scrollTo, virtualizer])

  useEffect(() => {
    const el = pane.current
    const key = focused ? [...focused].join(' ') : ''
    if (!focused) centred.current = ''
    if (!focused || !el || centred.current === key) return
    const inside = rows.flatMap((row, i) =>
      row.kind === 'record' && focused.has(row.record.id) ? [i] : [],
    )
    const at = (i: number) => virtualizer.measurementsCache[i]
    const first = at(inside[0])
    const last = at(inside[inside.length - 1])
    if (!first || !last) return
    centred.current = key
    const target =
      last.end - first.start <= el.clientHeight
        ? (first.start + last.end) / 2 - el.clientHeight / 2
        : first.start
    el.scrollTo?.({ behavior: 'smooth', top: Math.max(0, target) })
  }, [focused, rows, virtualizer])

  useLayoutEffect(() => {
    const index = moving.current
    if (index === null) return
    const row = pane.current?.querySelector<HTMLElement>(
      `[data-index="${index}"]`,
    )
    if (!row) return
    moving.current = null
    row.focus({ preventScroll: true })
  })

  const onKeyDown = (e: KeyboardEvent<HTMLTableSectionElement>) => {
    const move = MOVES[e.key]
    const row = (e.target as HTMLElement).closest<HTMLElement>('[data-index]')
    if (!move || !row || e.target !== row) return
    e.preventDefault()
    const next = Math.max(
      0,
      Math.min(
        rows.length - 1,
        move(Number(row.dataset.index), rows.length - 1),
      ),
    )
    setFocusKey(keyOf(next))
    virtualizer.scrollToIndex(next, { align: 'auto' })
    const target = pane.current?.querySelector<HTMLElement>(
      `[data-index="${next}"]`,
    )
    moving.current = target ? null : next
    target?.focus({ preventScroll: true })
  }

  const {
    after,
    afterSkipped,
    rows: shownRows,
  } = gapsOf(items, virtualizer.getTotalSize(), rows.length)
  const found = useCallback(
    (index: number) => scrollToFound(virtualizer, index),
    [virtualizer],
  )
  const stubs = (indexes: number[]) =>
    indexes.map((i) => (
      <FindStub
        index={i}
        key={keyOf(i)}
        onFound={found}
        text={findText(rows[i], turnStarts)}
      />
    ))

  return (
    <div
      className="@container/tj min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClear()
      }}
      onScroll={(e) => {
        const el = e.currentTarget
        following.current =
          el.scrollHeight - el.clientHeight - el.scrollTop <= 2
      }}
      ref={pane}
    >
      <table
        aria-label="Trajectory"
        aria-rowcount={rows.length}
        className="w-full table-fixed border-collapse text-sm leading-5"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClear()
        }}
        role="grid"
      >
        <colgroup>
          <col className="w-52 @max-[620px]/tj:w-13" />
          <col />
        </colgroup>
        <tbody
          onFocus={(e) => {
            const index = (e.target as HTMLElement).closest<HTMLElement>(
              '[data-index]',
            )?.dataset.index
            if (index !== undefined) setFocusKey(keyOf(Number(index)))
          }}
          onKeyDown={onKeyDown}
        >
          {shownRows.flatMap(({ before, item, skipped }) => {
            const row = rows[item.index]
            const i = item.index
            return [
              ...(before > 0 || skipped.length
                ? [
                    <Gap height={before} key={`gap-${item.key}`}>
                      {stubs(skipped)}
                    </Gap>,
                  ]
                : []),
              row.kind === 'summary' ? (
                <SummaryRow
                  index={i}
                  key={item.key}
                  measure={virtualizer.measureElement}
                  onFold={() => onFold(row.fold)}
                  text={row.text}
                />
              ) : (
                <RecordRow
                  active={activeTurn === row.record.turn}
                  focus={
                    focused
                      ? focused.has(row.record.id)
                        ? 'inside'
                        : 'outside'
                      : undefined
                  }
                  index={i}
                  key={item.key}
                  measure={virtualizer.measureElement}
                  onDoubleClick={() => onDoubleClick(row.record)}
                  onSelect={onSelect}
                  record={row.record}
                  request={requestAt.get(row.record.id)}
                  requestSelected={
                    selection?.type === 'request' &&
                    selection.assistant === row.record.id &&
                    row.record.kind === 'assistant'
                  }
                  selected={
                    selection?.type === 'record' &&
                    selection.id === row.record.id
                  }
                  turnStart={turnStarts.get(row.record.id)}
                />
              ),
            ]
          })}
          {(after > 0 || afterSkipped.length > 0) && (
            <Gap height={after}>{stubs(afterSkipped)}</Gap>
          )}
        </tbody>
      </table>
    </div>
  )
}

function Content({ record }: { record: TrajectoryRecord }) {
  if (record.tool) {
    const { args, name, result } = record.tool
    const request = `${name} ${args}`
    return (
      <span
        className={cn(
          'grid grid-cols-[clamp(180px,calc(36cqw-56px),480px)_minmax(0,1fr)] gap-2 font-tj-code text-[14px]',
          record.kind === 'subtool' && 'pl-6.5',
        )}
        title={`${request} → ${result || 'No output'}`}
      >
        <span className="truncate">
          <span className="text-(--tj-label-1)">{name}</span>
          <span className="ml-1.75 text-(--tj-label-2)">{args}</span>
        </span>
        <span className="truncate">
          <span className="mr-2 text-(--tj-caption)">→</span>
          <span
            className={cn(
              record.error
                ? 'text-(--tj-error)'
                : result
                  ? 'text-(--tj-label-2)'
                  : 'text-(--tj-caption)',
            )}
          >
            {result || 'No output'}
          </span>
        </span>
      </span>
    )
  }
  if (record.kind === 'assistant' && !record.text)
    return (
      <span className="block truncate text-(--tj-caption) italic opacity-70">
        (tool call only)
      </span>
    )
  return (
    <span className="block truncate" title={record.text}>
      {record.text}
    </span>
  )
}

function contentText(record: TrajectoryRecord): string {
  if (record.tool) {
    const { args, name, result } = record.tool
    return `${name} ${args} → ${result || 'No output'}`
  }
  if (record.kind === 'assistant' && !record.text) return '(tool call only)'
  return record.text
}

/** The text of a row as it renders, for the browser's find. */
function findText(
  row: LedgerProps['rows'][number],
  turnStarts: Map<string, number>,
): string {
  if (row.kind === 'summary') return row.text
  const { record } = row
  const turn = turnStarts.get(record.id)
  return [
    turn === undefined ? null : `Turn ${turn}`,
    KIND_LABEL[record.kind],
    contentText(record),
  ]
    .filter(Boolean)
    .join(' ')
}

function Gap({ children, height }: { children?: ReactNode; height: number }) {
  return (
    <tr aria-hidden style={{ height }}>
      <td className="p-0 align-top" colSpan={2}>
        {children}
      </td>
    </tr>
  )
}

function RecordRow({
  active,
  focus,
  index,
  measure,
  onDoubleClick,
  onSelect,
  record,
  request,
  requestSelected,
  selected,
  turnStart,
}: {
  active: boolean
  focus?: 'inside' | 'outside'
  index: number
  measure: (row: HTMLElement | null) => void
  onDoubleClick: () => void
  onSelect: (selection: TrajectorySelection) => void
  record: TrajectoryRecord
  request?: TrajectoryRequest
  requestSelected: boolean
  selected: boolean
  turnStart?: number
}) {
  const select = () => onSelect({ id: record.id, type: 'record' })
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      select()
    }
  }
  const label = [
    record.request ? `Request ${record.request}` : null,
    KIND_LABEL[record.kind],
    record.text,
  ]
    .filter(Boolean)
    .join(', ')
  const cell =
    'relative h-9 hairline-b border-(--tj-border-1) whitespace-nowrap'
  return (
    <tr
      aria-label={label}
      aria-rowindex={index + 1}
      aria-selected={selected}
      className={cn(
        'h-9 cursor-default transition-[background-color,opacity] duration-120 outline-none focus-visible:shadow-[inset_0_0_0_1px_var(--tj-brand)]',
        selected || requestSelected
          ? 'bg-action/10 inset-ring inset-ring-action/35'
          : 'hover:bg-(--tj-hover)',
        focus === 'outside' && 'opacity-[.24]',
      )}
      data-error={record.error || undefined}
      data-index={index}
      data-kind={record.kind}
      data-record={record.id}
      data-request-selected={requestSelected || undefined}
      data-selected={selected || undefined}
      data-timeline-focus={focus}
      data-turn-start={turnStart !== undefined || undefined}
      onClick={select}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
      ref={measure}
      tabIndex={0}
    >
      <td
        className={cn(
          cell,
          'overflow-visible pr-1 pl-9 @max-[620px]/tj:pr-0 @max-[620px]/tj:pl-7',
        )}
      >
        {active && (
          <span
            aria-hidden
            className={cn(
              'absolute inset-y-0 left-0 w-1',
              record.error ? 'bg-(--tj-turn-error)' : 'bg-(--tj-turn-accent)',
            )}
          />
        )}
        {selected && record.error && (
          <span
            aria-hidden
            className="absolute inset-y-0 left-0 w-1.5 bg-(--tj-error)"
          />
        )}
        {turnStart !== undefined && (
          <span
            className={cn(
              'absolute top-0 left-0 z-1 rounded-br-xs px-1.25 py-px font-tj-code text-[11px] leading-3.5 tabular-nums',
              active
                ? 'bg-(--tj-turn-accent) text-(--tj-label-2)'
                : 'bg-(--tj-bg-module) text-(--tj-label-3)',
            )}
          >
            <span className="@max-[620px]/tj:hidden">Turn {turnStart}</span>
            <span className="hidden @max-[620px]/tj:inline">#{turnStart}</span>
          </span>
        )}
        {request && (
          <RequestDot
            onSelect={() =>
              onSelect({ assistant: request.assistant, type: 'request' })
            }
            request={request}
            selected={requestSelected}
          />
        )}
        <span className="flex items-center justify-end gap-2">
          {record.startedAt !== null && Number.isFinite(record.startedAt) && (
            <time
              className="font-tj-code text-[11px] text-(--tj-label-3) tabular-nums @max-[620px]/tj:hidden"
              dateTime={new Date(record.startedAt).toISOString()}
              title={fullTime(record.startedAt)}
            >
              {clockTime(record.startedAt, true)}
            </time>
          )}
          <span className="flex w-19 justify-end @max-[620px]/tj:w-auto">
            <KindTag kind={record.kind} />
          </span>
        </span>
      </td>
      <td className={cn(cell, 'overflow-hidden pr-2 pl-1')}>
        <Content record={record} />
      </td>
    </tr>
  )
}

function RequestDot({
  onSelect,
  request,
  selected,
}: {
  onSelect: () => void
  request: TrajectoryRequest
  selected: boolean
}) {
  return (
    <button
      aria-label={`Request #${request.number}`}
      className="group/dot absolute top-[-8px] left-3 z-2 flex size-4 items-center justify-center outline-none"
      onClick={(e) => {
        e.stopPropagation()
        onSelect()
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      type="button"
    >
      <span
        className={cn(
          'size-1.25 rounded-full shadow-[0_0_0_2px_var(--tj-bg-1)] transition-colors group-hover/dot:bg-(--tj-select) group-focus-visible/dot:bg-(--tj-select)',
          selected
            ? 'bg-[color-mix(in_srgb,var(--tj-select)_18%,transparent)] shadow-[0_0_0_1.5px_var(--tj-select)]'
            : 'bg-(--tj-caption)',
        )}
      />
      <span className="hairline font-tj-code pointer-events-none invisible absolute top-1/2 left-4 -translate-x-1 -translate-y-1/2 rounded-xs border-(--tj-border-2) bg-(--tj-bg-1) px-1 text-[11px] leading-4 whitespace-nowrap text-(--tj-label-2) opacity-0 shadow-sm transition-[opacity,transform] group-hover/dot:visible group-hover/dot:translate-x-0 group-hover/dot:opacity-100 group-focus-visible/dot:visible group-focus-visible/dot:translate-x-0 group-focus-visible/dot:opacity-100">
        Request #{request.number}
      </span>
    </button>
  )
}

function SummaryRow({
  index,
  measure,
  onFold,
  text,
}: {
  index: number
  measure: (row: HTMLElement | null) => void
  onFold: () => void
  text: string
}) {
  return (
    <tr
      aria-expanded={false}
      aria-label={`Expand ${text}`}
      aria-rowindex={index + 1}
      className="h-6 cursor-pointer outline-none hover:bg-(--tj-hover) focus-visible:shadow-[inset_0_0_0_1px_var(--tj-brand)]"
      data-index={index}
      data-summary
      onClick={onFold}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onFold()
        }
      }}
      ref={measure}
      tabIndex={0}
    >
      <td className="hairline-b h-6 border-(--tj-border-1)" />
      <td className="hairline-b h-6 truncate border-(--tj-border-1) pr-2 pl-1 text-sm leading-5">
        <b className="mr-1 text-(--tj-label-3)">…</b>
        <span className="text-(--tj-label-2)">{text}</span>
      </td>
    </tr>
  )
}
