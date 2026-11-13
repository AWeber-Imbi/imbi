import { useCallback, useEffect, useMemo, useState } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import type { AgentTask, AgentTaskEvent } from '@/types'

import { TrajectoryLedger, type TrajectorySelection } from './TrajectoryLedger'
import {
  buildTrajectory,
  type Fold,
  type Folds,
  recordForSeq,
  rowsOf,
  type TrajectoryRecord,
} from './trajectoryModel'

/**
 * The Trajectory tab, after the DeepSeek Harness trajectory view: a
 * ledger of every record the task produced.
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
  const [folds, setFolds] = useState<Folds>(() => ({
    calls: new Set(),
    subcalls: new Set(),
    turns: new Set(),
  }))
  const [selection, setSelection] = useState<TrajectorySelection>(null)
  const [scrollTo, setScrollTo] = useState<null | string>(null)

  const { records, requests, turns } = trajectory
  const rows = useMemo(() => rowsOf(trajectory, folds, ''), [trajectory, folds])
  const turnStarts = useMemo(
    () => new Map(turns.map((t) => [t.first, t.number])),
    [turns],
  )
  const byId = useMemo(() => new Map(records.map((r) => [r.id, r])), [records])

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
      const next: Folds = {
        calls: new Set(prev.calls),
        subcalls: new Set(prev.subcalls),
        turns: new Set(prev.turns),
      }
      if (fold.type === 'turn') flip(next.turns, fold.key)
      else if (fold.type === 'calls') flip(next.calls, fold.key)
      else flip(next.subcalls, fold.key)
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

function flip<T>(set: Set<T>, key: T) {
  if (set.has(key)) set.delete(key)
  else set.add(key)
}

/** The folds with the ones that hide a record opened. */
function unfoldFor(
  folds: Folds,
  record: TrajectoryRecord,
  trajectory: ReturnType<typeof buildTrajectory>,
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
  const next: Folds = {
    calls: new Set(folds.calls),
    subcalls: new Set(folds.subcalls),
    turns: new Set(folds.turns),
  }
  next.turns.delete(record.turn)
  if (assistant) next.calls.delete(assistant.id)
  if (record.parent) next.subcalls.delete(record.parent)
  return next
}
