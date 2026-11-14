import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import { ChartGantt } from 'lucide-react'

import type { AgentTask, AgentTaskEvent } from '@/types'

import { ActivityEmpty, NoMatches } from './ActivityEmpty'
import { useSearchHighlight, useTaskSearch } from './taskSearch'
import { TaskCopyMenu } from './TaskToolbar'
import { type InspectorTab, TrajectoryInspector } from './TrajectoryInspector'
import { TrajectoryLedger, type TrajectorySelection } from './TrajectoryLedger'
import {
  buildTrajectory,
  type Fold,
  type FoldButton,
  foldKeys,
  type Folds,
  recordForSeq,
  rowsOf,
  spansOf,
  type Trajectory,
  type TrajectoryRecord,
} from './trajectoryModel'
import {
  focusedBy,
  TrajectoryOverview,
  type TrajectoryRange,
} from './TrajectoryOverview'
import { TrajectoryToolbar, useTrajectoryDuration } from './TrajectoryToolbar'
import type { TrajectoryWindow } from './trajectoryWindow'

/**
 * The Trajectory tab, after the DeepSeek Harness trajectory view: a
 * toolbar, a timing overview, and a ledger of every record the task
 * produced.
 */
export function TrajectoryTab({
  events,
  onShowInConversation,
  task,
}: {
  events: AgentTaskEvent[]
  /** Opens the conversation at the turn that holds this event. */
  onShowInConversation?: (seq: number) => void
  task: AgentTask
}) {
  const navigate = useNavigate()
  const { hash, pathname } = useLocation()
  const live = task.status !== 'closed'
  const trajectory = useMemo(
    () => buildTrajectory(events, live),
    [events, live],
  )
  const [folds, setFolds] = useState<Folds>(emptyFolds)
  const [selection, setSelection] = useState<TrajectorySelection>(null)
  const [scrollTo, setScrollTo] = useState<null | { id: string }>(null)
  const [visible, setVisible] = useState<null | TrajectoryWindow>(null)
  const [query, setQuery] = useTaskSearch()
  const root = useRef<HTMLDivElement>(null)
  useSearchHighlight(root, query)
  const [duration, setDuration] = useTrajectoryDuration()
  const [range, setRange] = useState<null | TrajectoryRange>(null)
  const [tab, setTab] = useState<InspectorTab>('Summary')

  const { records, requests, turns } = trajectory
  const mode = duration ? 'duration' : 'sequence'
  const rows = useMemo(
    () => rowsOf(trajectory, folds, query),
    [trajectory, folds, query],
  )
  const { domain, spans } = useMemo(
    () => spansOf(records, mode),
    [records, mode],
  )
  const focused = useMemo(() => focusedBy(spans, range), [spans, range])
  const matches = useMemo(
    () =>
      query.trim()
        ? new Set(
            rows.flatMap((r) => (r.kind === 'record' ? [r.record.id] : [])),
          )
        : null,
    [rows, query],
  )
  const turnStarts = useMemo(
    () => new Map(turns.map((t) => [t.first, t.number])),
    [turns],
  )
  const boundaries = useMemo(
    () =>
      turns
        .slice(1)
        .flatMap((t) => spans.filter((s) => s.id === t.first))
        .map((s) => s.start),
    [turns, spans],
  )
  const byId = useMemo(() => new Map(records.map((r) => [r.id, r])), [records])
  const keys = useMemo(
    () => ({
      calls: foldKeys(trajectory, 'calls'),
      subcalls: foldKeys(trajectory, 'subcalls'),
      turns: foldKeys(trajectory, 'turns'),
    }),
    [trajectory],
  )
  const folded = Object.fromEntries(
    (['turns', 'calls', 'subcalls'] as const).map((button) => {
      const set = folds[button] as Set<number | string>
      const list = keys[button]
      return [button, list.length ? list.every((k) => set.has(k)) : null]
    }),
  ) as Record<FoldButton, boolean | null>

  const reveal = useCallback(
    (record: TrajectoryRecord) => {
      setFolds((prev) => unfoldFor(prev, record, trajectory))
      setScrollTo({ id: record.id })
    },
    [trajectory],
  )

  const hides = useCallback(
    (q: string, id: string) =>
      !!q.trim() &&
      !rowsOf(trajectory, emptyFolds(), q).some(
        (r) => r.kind === 'record' && r.record.id === id,
      ),
    [trajectory],
  )

  const linked = /^#e(\d+)$/.exec(hash)?.[1]
  const handled = useRef<null | { exact: boolean; id: string; seq: string }>(
    null,
  )
  useEffect(() => {
    if (!linked) {
      handled.current = null
      return
    }
    const prev = handled.current
    if (
      prev?.seq === linked &&
      prev.exact &&
      byId.get(prev.id)?.seqs.includes(Number(linked))
    )
      return
    const record = recordForSeq(records, Number(linked))
    if (!record) return
    if (prev?.seq === linked && prev.id === record.id) return
    handled.current = {
      exact: record.seqs.includes(Number(linked)),
      id: record.id,
      seq: linked,
    }
    setSelection((prev) =>
      prev?.type === 'record' && prev.id === record.id
        ? prev
        : { id: record.id, type: 'record' },
    )
    setQuery((q) => (hides(q, record.id) ? '' : q))
    reveal(record)
  }, [byId, hides, linked, records, reveal])

  const select = useCallback(
    (next: TrajectorySelection) => {
      setSelection(next)
      if (next?.type !== 'record') return
      const id = next.id
      setQuery((q) => (hides(q, id) ? '' : q))
      if (focused && !focused.has(next.id)) setRange(null)
      const record = byId.get(next.id)
      const seq = record?.seqs.length ? Math.min(...record.seqs) : null
      if (seq !== null && hash !== `#e${seq}`)
        navigate(`${pathname}#e${seq}`, { replace: true })
    },
    [byId, focused, hash, hides, navigate, pathname],
  )

  const toggle = (fold: Fold) =>
    setFolds((prev) => {
      const next = copyFolds(prev)
      if (fold.type === 'turn') flip(next.turns, fold.key)
      else if (fold.type === 'calls') flip(next.calls, fold.key)
      else flip(next.subcalls, fold.key)
      return next
    })

  const foldAll = (button: FoldButton) => {
    const all = folded[button] === true
    setFolds((prev) => {
      const next = copyFolds(prev)
      const set = next[button] as Set<number | string>
      for (const k of keys[button]) {
        if (all) set.delete(k)
        else set.add(k)
      }
      return next
    })
  }

  const onDoubleClick = (record: TrajectoryRecord) => {
    if (folds.turns.has(record.turn))
      return toggle({ key: record.turn, type: 'turn' })
    const hasCalls =
      record.kind === 'assistant' &&
      records.some((r) => r.request === record.request && r.kind === 'tool')
    if (hasCalls) return toggle({ key: record.id, type: 'calls' })
    if (turnStarts.has(record.id)) toggle({ key: record.turn, type: 'turn' })
  }

  const selectedRecord =
    selection?.type === 'record' ? byId.get(selection.id) : undefined
  const selectedRequest =
    selection?.type === 'request'
      ? requests.find((r) => r.assistant === selection.assistant)
      : undefined

  const activeTurn =
    selection?.type === 'record'
      ? (byId.get(selection.id)?.turn ?? null)
      : selection?.type === 'request'
        ? (requests.find((r) => r.assistant === selection.assistant)?.turn ??
          null)
        : null

  return (
    <div
      className="trajectory isolate flex min-h-0 flex-1 flex-col overflow-hidden"
      ref={root}
    >
      <TrajectoryToolbar
        duration={duration}
        end={<TaskCopyMenu events={events} task={task} />}
        folded={folded}
        onDuration={(on) => {
          setDuration(on)
          setRange(null)
        }}
        onFold={foldAll}
        onQuery={setQuery}
        query={query}
      />
      <TrajectoryOverview
        boundaries={boundaries}
        domain={domain}
        key={mode}
        matches={matches}
        mode={mode}
        onRange={setRange}
        onSelect={(id) => {
          const record = byId.get(id)
          if (!record) return
          select({ id, type: 'record' })
          reveal(record)
        }}
        range={range}
        records={byId}
        selected={selection?.type === 'record' ? selection.id : null}
        spans={spans}
        visible={rows.length ? visible : null}
      />
      <div className="@container/tjpane relative flex min-h-0 flex-1 overflow-hidden">
        {rows.length === 0 ? (
          query.trim() ? (
            <NoMatches onClear={() => setQuery('')} query={query} />
          ) : (
            <ActivityEmpty icon={<ChartGantt />} title="No activity yet">
              No trajectory yet.
            </ActivityEmpty>
          )
        ) : (
          <TrajectoryLedger
            activeTurn={activeTurn}
            focused={focused}
            onClear={() => setSelection(null)}
            onDoubleClick={onDoubleClick}
            onFold={toggle}
            onSelect={select}
            onVisible={setVisible}
            requests={requests}
            rows={rows}
            scrollTo={scrollTo}
            selection={selection}
            turnStarts={turnStarts}
          />
        )}
        {(selectedRecord || selectedRequest) && (
          <TrajectoryInspector
            inspected={
              selectedRecord
                ? { record: selectedRecord, type: 'record' }
                : { request: selectedRequest!, type: 'request' }
            }
            live={live}
            onClose={() => setSelection(null)}
            onSelect={(target) => {
              if (target.type === 'request') {
                select({
                  assistant: target.request.assistant,
                  type: 'request',
                })
                return
              }
              select({ id: target.record.id, type: 'record' })
              reveal(target.record)
            }}
            onShowInConversation={onShowInConversation}
            onTab={setTab}
            tab={tab}
            trajectory={trajectory}
          />
        )}
      </div>
    </div>
  )
}

function copyFolds(folds: Folds): Folds {
  return {
    calls: new Set(folds.calls),
    subcalls: new Set(folds.subcalls),
    turns: new Set(folds.turns),
  }
}

function emptyFolds(): Folds {
  return { calls: new Set(), subcalls: new Set(), turns: new Set() }
}

function flip<T>(set: Set<T>, key: T) {
  if (set.has(key)) set.delete(key)
  else set.add(key)
}

/** The folds with the ones that hide a record opened. */
function unfoldFor(
  folds: Folds,
  record: TrajectoryRecord,
  trajectory: Trajectory,
): Folds {
  const assistant = trajectory.records.find(
    (r) => r.kind === 'assistant' && r.request === record.request,
  )
  const hidden =
    folds.turns.has(record.turn) ||
    (!!assistant &&
      record.kind !== 'assistant' &&
      folds.calls.has(assistant.id)) ||
    (!!record.parent && folds.subcalls.has(record.parent))
  if (!hidden) return folds
  const next = copyFolds(folds)
  next.turns.delete(record.turn)
  if (assistant) next.calls.delete(assistant.id)
  if (record.parent) next.subcalls.delete(record.parent)
  return next
}
