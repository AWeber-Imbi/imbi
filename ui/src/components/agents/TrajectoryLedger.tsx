import { type KeyboardEvent, useEffect, useLayoutEffect, useRef } from 'react'

import { Info, Settings, Sparkle, User, Wrench } from 'lucide-react'

import { cn } from '@/lib/utils'

import {
  type Fold,
  KIND_LABEL,
  type TrajectoryKind,
  type TrajectoryRecord,
  type TrajectoryRequest,
  type TrajectoryRow,
} from './trajectoryModel'

export type TrajectorySelection =
  | null
  | { id: string; type: 'record' }
  | { number: number; type: 'request' }

const TAG: Record<TrajectoryKind, string> = {
  assistant:
    'w-full justify-center bg-(--tj-assistant-bg) text-(--tj-assistant)',
  context: 'bg-(--tj-success-3) text-(--tj-context)',
  subtool: 'bg-(--tj-subtool-bg) text-(--tj-subtool)',
  system: 'bg-(--tj-bg-module) text-(--tj-label-2)',
  tool: 'bg-(--tj-warn-3) text-(--tj-warn)',
  user: 'bg-(--tj-business-3) text-(--tj-business)',
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
  /** Keeps the ledger at the bottom while the task runs. */
  live: boolean
  onClear: () => void
  onDoubleClick: (record: TrajectoryRecord) => void
  onFold: (fold: Fold) => void
  onSelect: (selection: TrajectorySelection) => void
  requests: TrajectoryRequest[]
  rows: TrajectoryRow[]
  /** A new object scrolls the ledger to that record. */
  scrollTo: null | { id: string }
  selection: TrajectorySelection
  /** The turn number at the row where each turn starts. */
  turnStarts: Map<string, number>
}

/** The kind tag of a record: a label, or an icon when the table is narrow. */
export function KindTag({ kind }: { kind: TrajectoryKind }) {
  const Icon = ICON[kind]
  return (
    <span
      className={cn(
        'inline-flex h-4.75 shrink-0 items-center rounded-[4px] px-1.25 text-[10px] leading-4 font-[650] tracking-[.035em] uppercase @max-[620px]/tj:w-4.75 @max-[620px]/tj:justify-center @max-[620px]/tj:px-0',
        TAG[kind],
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
  live,
  onClear,
  onDoubleClick,
  onFold,
  onSelect,
  requests,
  rows,
  scrollTo,
  selection,
  turnStarts,
}: LedgerProps) {
  const pane = useRef<HTMLDivElement>(null)
  const following = useRef(live)
  const requestAt = new Map(requests.map((r) => [r.assistant, r]))

  useLayoutEffect(() => {
    const el = pane.current
    if (el && following.current) el.scrollTop = el.scrollHeight
  }, [rows.length])

  useEffect(() => {
    if (!scrollTo) return
    const row = [
      ...(pane.current?.querySelectorAll<HTMLElement>('[data-record]') ?? []),
    ].find((el) => el.dataset.record === scrollTo.id)
    row?.scrollIntoView?.({ block: 'nearest' })
  }, [scrollTo])

  useEffect(() => {
    const el = pane.current
    if (!focused || !el) return
    const inside = [
      ...el.querySelectorAll<HTMLElement>('[data-timeline-focus="inside"]'),
    ]
    if (!inside.length) return
    const last = inside[inside.length - 1]
    const top = inside[0].offsetTop
    const bottom = last.offsetTop + last.offsetHeight
    const target =
      bottom - top <= el.clientHeight
        ? (top + bottom) / 2 - el.clientHeight / 2
        : top
    el.scrollTo?.({ behavior: 'smooth', top: Math.max(0, target) })
  }, [focused])

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
        className="w-full table-fixed border-collapse text-[12px] leading-[18px]"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClear()
        }}
        role="grid"
      >
        <colgroup>
          <col className="w-30.5 @max-[620px]/tj:w-12.5" />
          <col />
        </colgroup>
        <tbody>
          {rows.map((row, i) =>
            row.kind === 'summary' ? (
              <SummaryRow
                index={i}
                key={row.id}
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
                key={row.record.id}
                onDoubleClick={() => onDoubleClick(row.record)}
                onSelect={onSelect}
                record={row.record}
                request={requestAt.get(row.record.id)}
                requestSelected={
                  selection?.type === 'request' &&
                  selection.number === row.record.request &&
                  row.record.kind === 'assistant'
                }
                selected={
                  selection?.type === 'record' && selection.id === row.record.id
                }
                turnStart={turnStarts.get(row.record.id)}
              />
            ),
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
          'grid grid-cols-[clamp(180px,calc(36cqw-56px),480px)_minmax(0,1fr)] gap-2 font-tj-code',
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
      <span className="block truncate text-(--tj-label-3)">
        (tool call only)
      </span>
    )
  return (
    <span className="block truncate" title={record.text}>
      {record.text}
    </span>
  )
}

function RecordRow({
  active,
  focus,
  index,
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
    'relative h-[30px] hairline-b border-(--tj-border-1) whitespace-nowrap'
  return (
    <tr
      aria-label={label}
      aria-rowindex={index + 1}
      aria-selected={selected}
      className={cn(
        'h-7.5 cursor-default transition-[background-color,opacity] duration-120 outline-none hover:bg-(--tj-hover) focus-visible:shadow-[inset_0_0_0_1px_var(--tj-business)]',
        selected && 'bg-(--tj-active) hover:bg-(--tj-active)',
        focus === 'outside' && 'opacity-[.24]',
      )}
      data-error={record.error || undefined}
      data-kind={record.kind}
      data-record={record.id}
      data-selected={selected || undefined}
      data-timeline-focus={focus}
      data-turn-start={turnStart !== undefined || undefined}
      onClick={select}
      onDoubleClick={onDoubleClick}
      onKeyDown={onKeyDown}
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
              'absolute inset-y-0 left-0 w-0.5',
              record.error ? 'bg-(--tj-turn-error)' : 'bg-(--tj-turn-accent)',
            )}
          />
        )}
        {selected && (
          <span
            aria-hidden
            className={cn(
              'absolute inset-y-0 left-0 w-0.75',
              record.error ? 'bg-(--tj-error)' : 'bg-(--tj-brand)',
            )}
          />
        )}
        {turnStart !== undefined && (
          <span
            className={cn(
              'absolute top-0 left-0 z-1 rounded-br-xs px-1.25 py-px font-tj-code text-[8px] leading-2.5 tabular-nums',
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
              onSelect({ number: request.number, type: 'request' })
            }
            request={request}
            selected={requestSelected}
          />
        )}
        <span className="flex justify-end">
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
      type="button"
    >
      <span
        className={cn(
          'size-1.25 rounded-full shadow-[0_0_0_2px_var(--tj-bg-1)] transition-colors group-hover/dot:bg-(--tj-brand) group-focus-visible/dot:bg-(--tj-brand)',
          selected
            ? 'bg-[color-mix(in_srgb,var(--tj-brand)_18%,transparent)] shadow-[0_0_0_1.5px_var(--tj-business)]'
            : 'bg-(--tj-caption)',
        )}
      />
      <span className="hairline font-tj-code pointer-events-none invisible absolute top-1/2 left-4 -translate-x-1 -translate-y-1/2 rounded-xs border-(--tj-border-2) bg-(--tj-bg-1) px-1 text-[9px] leading-3 whitespace-nowrap text-(--tj-label-2) opacity-0 shadow-[0_2px_6px_rgba(0,0,0,.12)] transition-[opacity,transform] group-hover/dot:visible group-hover/dot:translate-x-0 group-hover/dot:opacity-100 group-focus-visible/dot:visible group-focus-visible/dot:translate-x-0 group-focus-visible/dot:opacity-100">
        Request #{request.number}
      </span>
    </button>
  )
}

function SummaryRow({
  index,
  onFold,
  text,
}: {
  index: number
  onFold: () => void
  text: string
}) {
  return (
    <tr
      aria-rowindex={index + 1}
      className="h-5 cursor-pointer outline-none hover:bg-(--tj-hover) focus-visible:shadow-[inset_0_0_0_1px_var(--tj-business)]"
      data-summary
      onClick={onFold}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onFold()
        }
      }}
      tabIndex={0}
    >
      <td className="hairline-b h-5 border-(--tj-border-1)" />
      <td className="hairline-b h-5 truncate border-(--tj-border-1) pr-2 pl-1 text-[12px] leading-4">
        <b className="mr-1 text-(--tj-label-3)">…</b>
        <span className="text-(--tj-label-2)">{text}</span>
      </td>
    </tr>
  )
}
