import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

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
  type TrajectorySpan,
} from './trajectoryModel'
import {
  focusedBy,
  TrajectoryOverview,
  type TrajectoryRange,
} from './TrajectoryOverview'
import { TrajectoryToolbar, useTrajectoryDuration } from './TrajectoryToolbar'
import type { TrajectoryWindow } from './trajectoryWindow'
import { useStoredState } from './useStoredState'

/** The records a range covered when picked, and its edges from theirs. */
interface Picked {
  ids: Set<string>
  lead: number
  tail: number
}

/**
 * The Trajectory tab, after the DeepSeek Harness trajectory view: a
 * toolbar, a timing overview, and a ledger of every record the task
 * produced.
 */
const FOLD_BUTTONS: readonly FoldButton[] = ['turns', 'calls', 'subcalls']

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
  const [foldPrefs, setFoldPrefs] = useStoredState<FoldButton[]>(
    'imbi.trajectory.folds',
    [],
    (v) =>
      Array.isArray(v)
        ? v.filter((b): b is FoldButton => FOLD_BUTTONS.includes(b))
        : undefined,
  )
  const seen = useRef<Set<string>>(new Set())
  const [selection, setSelection] = useState<TrajectorySelection>(null)
  const [scrollTo, setScrollTo] = useState<null | { id: string }>(null)
  const [visible, setVisible] = useState<null | TrajectoryWindow>(null)
  const [query, setQuery] = useTaskSearch()
  const root = useRef<HTMLDivElement>(null)
  useSearchHighlight(root, query)
  const [duration, setDuration] = useTrajectoryDuration()
  const [picked, setPicked] = useState<null | Picked>(null)
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
  const range = useMemo(() => rangeOf(spans, picked), [spans, picked])
  const focused = range ? picked!.ids : null
  const setRange = useCallback(
    (next: null | TrajectoryRange) => {
      const ids = focusedBy(spans, next)
      const hull = ids && hullOf(spans, ids)
      setPicked(
        next && ids && hull
          ? { ids, lead: next[0] - hull[0], tail: next[1] - hull[1] }
          : null,
      )
    },
    [spans],
  )
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
  const linked = /^#e(\d+)$/.exec(hash)?.[1]
  const handled = useRef<null | { exact: boolean; id: string; seq: string }>(
    null,
  )
  useLayoutEffect(() => {
    let fresh = emptyFolds()
    let any = false
    for (const button of FOLD_BUTTONS) {
      for (const k of keys[button]) {
        const id = `${button}:${k}`
        if (seen.current.has(id)) continue
        seen.current.add(id)
        if (!foldPrefs.includes(button)) continue
        ;(fresh[button] as Set<number | string>).add(k)
        any = true
      }
    }
    if (!any) return
    const target =
      linked && handled.current?.seq === linked
        ? byId.get(handled.current.id)
        : undefined
    if (target) fresh = unfoldFor(fresh, target, trajectory)
    setFolds((prev) => {
      const next = copyFolds(prev)
      for (const button of FOLD_BUTTONS)
        for (const k of fresh[button] as Set<number | string>)
          (next[button] as Set<number | string>).add(k)
      return next
    })
  }, [byId, foldPrefs, keys, linked, trajectory])

  const folded = Object.fromEntries(
    (['turns', 'calls', 'subcalls'] as const).map((button) => {
      return [button, keys[button].length ? foldPrefs.includes(button) : null]
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
      if (focused && !focused.has(next.id)) setPicked(null)
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
    setFoldPrefs(
      all
        ? foldPrefs.filter((b) => b !== button)
        : [...new Set([...foldPrefs, button])],
    )
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
          setPicked(null)
        }}
        onFold={foldAll}
        onQuery={setQuery}
        query={query}
      />
      <TrajectoryOverview
        boundaries={boundaries}
        domain={domain}
        focused={focused}
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
        {rows.length > 0 && (selectedRecord || selectedRequest) && (
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

function hullOf(
  spans: TrajectorySpan[],
  ids: Set<string>,
): null | TrajectoryRange {
  const mine = spans.filter((s) => ids.has(s.id))
  if (!mine.length) return null
  return [
    Math.min(...mine.map((s) => s.start)),
    Math.max(...mine.map((s) => s.end)),
  ]
}

function rangeOf(
  spans: TrajectorySpan[],
  picked: null | Picked,
): null | TrajectoryRange {
  const hull = picked && hullOf(spans, picked.ids)
  if (!hull) return null
  const kept = spans.filter((s) => picked!.ids.has(s.id)).length
  const start = hull[0] + picked!.lead
  const end = hull[1] + picked!.tail
  return kept === picked!.ids.size && start <= end ? [start, end] : hull
}

/** The folds with the ones that hide a record opened. */
function unfoldFor(
  folds: Folds,
  record: TrajectoryRecord,
  trajectory: Trajectory,
): Folds {
  const turn = trajectory.turns.find((t) => t.number === record.turn)
  const byTurn = folds.turns.has(record.turn)
  if (byTurn && turn?.first === record.id) return folds
  const call = record.kind === 'tool' || record.kind === 'subtool'
  const assistant = call
    ? trajectory.records.find(
        (r) => r.kind === 'assistant' && r.request === record.request,
      )
    : undefined
  const byCalls = !!assistant && folds.calls.has(assistant.id)
  const parent = call ? record.parent : null
  const bySubcalls = !!parent && folds.subcalls.has(parent)
  if (!byTurn && !byCalls && !bySubcalls) return folds
  const next = copyFolds(folds)
  if (byTurn) next.turns.delete(record.turn)
  if (byCalls) next.calls.delete(assistant.id)
  if (bySubcalls) next.subcalls.delete(parent)
  return next
}
