import { useCallback, useEffect, useMemo, useState } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import type { AgentTask, AgentTaskEvent } from '@/types'

import { TrajectoryLedger, type TrajectorySelection } from './TrajectoryLedger'
import {
  buildTrajectory,
  type Fold,
  type FoldButton,
  foldKeys,
  type Folds,
  recordForSeq,
  rowsOf,
  type Trajectory,
  type TrajectoryRecord,
} from './trajectoryModel'
import { TrajectoryToolbar, useTrajectoryDuration } from './TrajectoryToolbar'

const SET_OF: Record<FoldButton, keyof Folds> = {
  calls: 'calls',
  subcalls: 'subcalls',
  turns: 'turns',
}

/**
 * The Trajectory tab, after the DeepSeek Harness trajectory view: a
 * toolbar and a ledger of every record the task produced.
 */
export function TrajectoryTab({
  events,
  task,
}: {
  events: AgentTaskEvent[]
  task: AgentTask
}) {
  const navigate = useNavigate()
  const { hash, pathname } = useLocation()
  const live = task.status === 'running'
  const trajectory = useMemo(
    () => buildTrajectory(events, live),
    [events, live],
  )
  const [folds, setFolds] = useState<Folds>(emptyFolds)
  const [selection, setSelection] = useState<TrajectorySelection>(null)
  const [scrollTo, setScrollTo] = useState<null | string>(null)
  const [query, setQuery] = useState('')
  const [duration, setDuration] = useTrajectoryDuration()

  const { records, requests, turns } = trajectory
  const rows = useMemo(
    () => rowsOf(trajectory, folds, query),
    [trajectory, folds, query],
  )
  const turnStarts = useMemo(
    () => new Map(turns.map((t) => [t.first, t.number])),
    [turns],
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
      const set = folds[SET_OF[button]] as Set<number | string>
      const list = keys[button]
      return [button, list.length ? list.every((k) => set.has(k)) : null]
    }),
  ) as Record<FoldButton, boolean | null>

  const linked = /^#e(\d+)$/.exec(hash)?.[1]
  useEffect(() => {
    if (!linked) return
    const record = recordForSeq(records, Number(linked))
    if (!record) return
    setSelection((prev) =>
      prev?.type === 'record' && prev.id === record.id
        ? prev
        : { id: record.id, type: 'record' },
    )
    setFolds((prev) => unfoldFor(prev, record, trajectory))
    setScrollTo(record.id)
  }, [linked, records, trajectory])

  const select = useCallback(
    (next: TrajectorySelection) => {
      setSelection(next)
      if (next?.type !== 'record') return
      const record = byId.get(next.id)
      const seq = record?.seqs.length ? Math.min(...record.seqs) : null
      if (seq !== null && hash !== `#e${seq}`)
        navigate(`${pathname}#e${seq}`, { replace: true })
    },
    [byId, hash, navigate, pathname],
  )

  const toggle = (fold: Fold) =>
    setFolds((prev) => {
      const next = copyFolds(prev)
      if (fold.type === 'turn') flip(next.turns, fold.key)
      else if (fold.type === 'calls') flip(next.calls, fold.key)
      else flip(next.subcalls, fold.key)
      return next
    })

  const foldAll = (button: FoldButton) =>
    setFolds((prev) => {
      const next = copyFolds(prev)
      const set = next[SET_OF[button]] as Set<number | string>
      const list = keys[button]
      const all = list.every((k) => set.has(k))
      for (const k of list) {
        if (all) set.delete(k)
        else set.add(k)
      }
      return next
    })

  const onDoubleClick = (record: TrajectoryRecord) => {
    if (folds.turns.has(record.turn))
      return toggle({ key: record.turn, type: 'turn' })
    const hasCalls =
      record.kind === 'assistant' &&
      records.some((r) => r.request === record.request && r.kind === 'tool')
    if (hasCalls) return toggle({ key: record.id, type: 'calls' })
    if (turnStarts.has(record.id)) toggle({ key: record.turn, type: 'turn' })
  }

  const activeTurn =
    selection?.type === 'record'
      ? (byId.get(selection.id)?.turn ?? null)
      : selection?.type === 'request'
        ? (requests.find((r) => r.number === selection.number)?.turn ?? null)
        : null

  return (
    <div className="trajectory isolate flex min-h-0 flex-1 flex-col overflow-hidden">
      <TrajectoryToolbar
        duration={duration}
        folded={folded}
        onDuration={setDuration}
        onFold={foldAll}
        onQuery={setQuery}
        query={query}
      />
      <TrajectoryLedger
        activeTurn={activeTurn}
        focused={null}
        onClear={() => setSelection(null)}
        onDoubleClick={onDoubleClick}
        onFold={toggle}
        onSelect={select}
        requests={requests}
        rows={rows}
        scrollTo={scrollTo}
        selection={selection}
        turnStarts={turnStarts}
      />
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
