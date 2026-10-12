import {
  type DragEvent,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from 'react'

import { Maximize, Minus, Plus, X } from 'lucide-react'

import { cn } from '@/lib/utils'

import { CanvasNode, type NodeSummary } from './CanvasNode'
import {
  edgePath,
  fitView,
  GRID,
  inPoint,
  NODE_W,
  outPoint,
  type Point,
  portsOf,
  snap,
  type StepTypes,
  toCanvas,
  type View,
  zoomAt,
} from './graph'
import { QuickAddMenu } from './QuickAddMenu'
import { CATEGORY_TILE, stepIcon } from './stepStyle'
import type { StepType, WorkflowGraph } from './types'

export type Selection =
  | null
  | { id: string; kind: 'node' }
  | { index: number; kind: 'edge' }

export const STEP_MIME = 'application/x-imbi-workflow-step'

interface CanvasProps {
  edgeErrors: Set<number>
  graph: WorkflowGraph
  onAdd: (
    type: StepType,
    position: Point,
    from?: { port: number; source: string },
  ) => void
  onConnect: (edge: { port: number; source: string; target: string }) => void
  onMove: (id: string, position: Point) => void
  onOpenPalette: (() => void) | null
  onRemoveEdge: (index: number) => void
  onSelect: (selection: Selection) => void
  onView: (view: View) => void
  readOnly: boolean
  selection: Selection
  summaries: Record<string, NodeSummary>
  types: StepTypes
  view: View
  viewportRef: RefObject<HTMLDivElement | null>
}

type Drag =
  | { id: string; kind: 'node'; moved: boolean; origin: Point; start: Point }
  | { kind: 'connect'; port: number; source: string }
  | { kind: 'pan'; moved: boolean; start: Point; view: View }

interface Quick {
  at: Point
  canvas: Point
  from: { port: number; source: string }
}

export function Canvas({
  edgeErrors,
  graph,
  onAdd,
  onConnect,
  onMove,
  onOpenPalette,
  onRemoveEdge,
  onSelect,
  onView,
  readOnly,
  selection,
  summaries,
  types,
  view,
  viewportRef,
}: CanvasProps) {
  const [temp, setTemp] = useState<null | { a: Point; b: Point }>(null)
  const [quick, setQuick] = useState<null | Quick>(null)
  const [panning, setPanning] = useState(false)
  // Latest props for the window listeners of a drag in progress.
  const latest = useRef({ graph, onConnect, onMove, onSelect, onView, view })
  latest.current = { graph, onConnect, onMove, onSelect, onView, view }

  // React registers wheel listeners as passive, so preventDefault needs
  // a native listener.
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = latest.current.view
      if (e.ctrlKey || e.metaKey) {
        const r = el.getBoundingClientRect()
        latest.current.onView(
          zoomAt(
            v,
            { x: e.clientX - r.left, y: e.clientY - r.top },
            Math.exp(-e.deltaY * 0.01),
          ),
        )
      } else {
        latest.current.onView({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY })
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [viewportRef])

  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === 'Escape' && setQuick(null)
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  const origin = (): Point => {
    const r = viewportRef.current!.getBoundingClientRect()
    return { x: r.left, y: r.top }
  }

  const startDrag = (drag: Drag) => {
    const move = (e: PointerEvent) => {
      const client = { x: e.clientX, y: e.clientY }
      const { graph: g, view: v } = latest.current
      if (drag.kind === 'pan') {
        const dx = client.x - drag.start.x
        const dy = client.y - drag.start.y
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true
        latest.current.onView({
          ...drag.view,
          x: drag.view.x + dx,
          y: drag.view.y + dy,
        })
      } else if (drag.kind === 'node') {
        const dx = (client.x - drag.start.x) / v.zoom
        const dy = (client.y - drag.start.y) / v.zoom
        if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 3) return
        drag.moved = true
        const node = g.nodes.find((n) => n.id === drag.id)
        const x = snap(drag.origin.x + dx)
        const y = snap(drag.origin.y + dy)
        if (node && (node.position.x !== x || node.position.y !== y)) {
          latest.current.onMove(drag.id, { x, y })
        }
      } else {
        const b = toCanvas(client, origin(), v)
        setTemp((t) => (t ? { ...t, b } : t))
      }
    }
    const up = (e: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setPanning(false)
      if (drag.kind === 'pan' && !drag.moved) latest.current.onSelect(null)
      if (drag.kind !== 'connect') return
      setTemp(null)
      const hit = document
        .elementFromPoint(e.clientX, e.clientY)
        ?.closest('[data-node-id]')
      const from = { port: drag.port, source: drag.source }
      if (hit) {
        latest.current.onConnect({
          ...from,
          target: hit.getAttribute('data-node-id')!,
        })
        return
      }
      const r = viewportRef.current?.getBoundingClientRect()
      if (
        r &&
        e.clientX > r.left &&
        e.clientX < r.right &&
        e.clientY > r.top &&
        e.clientY < r.bottom
      ) {
        const at = { x: e.clientX - r.left, y: e.clientY - r.top }
        setQuick({
          at: {
            x: Math.min(at.x, r.width - 290),
            y: Math.min(at.y, r.height - 360),
          },
          canvas: toCanvas(
            { x: e.clientX, y: e.clientY },
            origin(),
            latest.current.view,
          ),
          from,
        })
      }
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const onBackgroundDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return
    setQuick(null)
    setPanning(true)
    startDrag({
      kind: 'pan',
      moved: false,
      start: { x: e.clientX, y: e.clientY },
      view,
    })
  }

  const onNodeDown = (e: ReactPointerEvent, id: string) => {
    if (e.button !== 0) return
    e.stopPropagation()
    setQuick(null)
    onSelect({ id, kind: 'node' })
    const node = graph.nodes.find((n) => n.id === id)
    if (!node || readOnly) return
    startDrag({
      id,
      kind: 'node',
      moved: false,
      origin: node.position,
      start: { x: e.clientX, y: e.clientY },
    })
  }

  const onPortDown = (e: ReactPointerEvent, id: string, port: number) => {
    if (e.button !== 0 || readOnly) return
    e.stopPropagation()
    setQuick(null)
    const node = graph.nodes.find((n) => n.id === id)!
    const a = outPoint(node, portsOf(node, types), port)
    setTemp({ a, b: a })
    startDrag({ kind: 'connect', port, source: id })
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    const type = types[e.dataTransfer.getData(STEP_MIME)]
    if (!type || readOnly) return
    const c = toCanvas({ x: e.clientX, y: e.clientY }, origin(), view)
    onAdd(type, { x: c.x - NODE_W / 2, y: c.y - 28 })
  }

  const fit = () => {
    const el = viewportRef.current
    if (el) onView(fitView(graph, types, el.clientWidth, el.clientHeight))
  }
  const zoomBy = (factor: number) => {
    const el = viewportRef.current
    if (!el) return
    onView(
      zoomAt(view, { x: el.clientWidth / 2, y: el.clientHeight / 2 }, factor),
    )
  }

  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const used = new Set(graph.edges.map((e) => `${e.source}:${e.port}`))
  const selectedEdge = selection?.kind === 'edge' ? selection.index : -1
  const triggers = Object.values(types).filter((t) => t.trigger)
  const grid = GRID * view.zoom

  return (
    <div
      className={cn(
        'bg-secondary relative min-h-0 flex-1 overflow-hidden touch-none',
        panning ? 'cursor-grabbing' : 'cursor-default',
      )}
      onDragOver={(e) => {
        e.preventDefault()
        e.dataTransfer.dropEffect = 'copy'
      }}
      onDrop={onDrop}
      onPointerDown={onBackgroundDown}
      ref={viewportRef}
    >
      <svg
        aria-hidden
        className="pointer-events-none absolute inset-0 size-full"
      >
        <defs>
          <pattern
            height={grid}
            id="workflow-grid"
            patternUnits="userSpaceOnUse"
            width={grid}
            x={view.x}
            y={view.y}
          >
            <circle
              className="fill-(--ds-border-primary)"
              cx={1}
              cy={1}
              r={1}
            />
          </pattern>
        </defs>
        <rect fill="url(#workflow-grid)" height="100%" width="100%" />
      </svg>

      <div
        className="absolute top-0 left-0 origin-top-left"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
        }}
      >
        <svg
          className="pointer-events-none absolute top-0 left-0 overflow-visible"
          height={1}
          width={1}
        >
          {graph.edges.map((edge, i) => {
            const a = byId.get(edge.source)
            const b = byId.get(edge.target)
            if (!a || !b) return null
            const path = edgePath(
              outPoint(a, portsOf(a, types), edge.port),
              inPoint(b),
            )
            const on = i === selectedEdge
            return (
              <g key={`${edge.source}:${edge.port}:${edge.target}`}>
                <path
                  className="cursor-pointer"
                  d={path.d}
                  fill="none"
                  onPointerDown={(e) => {
                    e.stopPropagation()
                    setQuick(null)
                    onSelect({ index: i, kind: 'edge' })
                  }}
                  stroke="transparent"
                  strokeWidth={14}
                  style={{ pointerEvents: 'stroke' }}
                />
                <path
                  className={cn(
                    on
                      ? 'stroke-[#ef9f27]'
                      : edgeErrors.has(i)
                        ? 'stroke-(--ds-text-danger)'
                        : 'stroke-(--ds-border-primary)',
                  )}
                  d={path.d}
                  fill="none"
                  strokeWidth={on ? 2.5 : 2}
                />
              </g>
            )
          })}
          {temp && (
            <path
              className="stroke-[#ef9f27]"
              d={edgePath(temp.a, temp.b).d}
              fill="none"
              strokeDasharray="6 5"
              strokeWidth={2}
            />
          )}
        </svg>

        {graph.nodes.map((node) => (
          <CanvasNode
            key={node.id}
            node={node}
            onPointerDown={(e) => onNodeDown(e, node.id)}
            onPortDown={(e, port) => onPortDown(e, node.id, port)}
            ports={portsOf(node, types)}
            selected={selection?.kind === 'node' && selection.id === node.id}
            summary={summaries[node.id]}
            type={types[node.type]}
            usedPorts={
              new Set(
                portsOf(node, types)
                  .map((_, i) => i)
                  .filter((i) => used.has(`${node.id}:${i}`)),
              )
            }
          />
        ))}

        {selectedEdge >= 0 && !readOnly && (
          <EdgeRemoveButton
            graph={graph}
            index={selectedEdge}
            onRemove={onRemoveEdge}
            types={types}
          />
        )}
      </div>

      {graph.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div
            className="border-tertiary bg-primary pointer-events-auto flex w-85 flex-col gap-3 rounded-xl border p-5"
            onPointerDown={(e) => e.stopPropagation()}
          >
            <div className="flex flex-col gap-1">
              <span className="font-medium">Choose a trigger</span>
              <span className="text-secondary text-sm">
                Every workflow starts with one. You can add more later.
              </span>
            </div>
            {triggers.map((t) => {
              const Icon = stepIcon(t.type, t.category)
              return (
                <button
                  className="border-tertiary hover:border-amber-border flex items-center gap-3 rounded-md border p-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={readOnly}
                  key={t.type}
                  onClick={() => {
                    const el = viewportRef.current!
                    const c = toCanvas(
                      { x: el.clientWidth / 2, y: el.clientHeight / 2 },
                      { x: 0, y: 0 },
                      view,
                    )
                    onAdd(t, { x: c.x - NODE_W / 2, y: c.y - 47 })
                  }}
                  type="button"
                >
                  <span
                    className={cn(
                      'flex size-8 shrink-0 items-center justify-center rounded-md',
                      CATEGORY_TILE.trigger,
                    )}
                  >
                    <Icon className="size-4" />
                  </span>
                  <span className="flex flex-col">
                    <span className="text-sm font-medium">{t.label}</span>
                    <span className="text-tertiary text-xs">
                      {t.description}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {onOpenPalette && (
        <button
          className="border-tertiary bg-primary hover:bg-secondary absolute top-4 left-4 flex h-8.5 items-center gap-1.5 rounded-md border px-3 text-sm font-medium"
          onClick={onOpenPalette}
          onPointerDown={(e) => e.stopPropagation()}
          type="button"
        >
          <Plus className="size-3.5" />
          Add step
        </button>
      )}

      {quick && (
        <QuickAddMenu
          at={quick.at}
          onPick={(type) => {
            onAdd(
              type,
              { x: quick.canvas.x, y: quick.canvas.y - 28 },
              quick.from,
            )
            setQuick(null)
          }}
          types={Object.values(types).filter((t) => !t.trigger)}
        />
      )}

      <div
        className="border-tertiary bg-primary absolute bottom-4 left-4 flex items-center overflow-hidden rounded-md border"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <ZoomButton label="Zoom out" onClick={() => zoomBy(1 / 1.2)}>
          <Minus className="size-3.5" />
        </ZoomButton>
        <span className="w-12 text-center font-mono text-xs">
          {Math.round(view.zoom * 100)}%
        </span>
        <ZoomButton label="Zoom in" onClick={() => zoomBy(1.2)}>
          <Plus className="size-3.5" />
        </ZoomButton>
        <span className="h-4.5 w-px bg-(--ds-border-tertiary)" />
        <ZoomButton label="Fit to view" onClick={fit}>
          <Maximize className="size-3.5" />
        </ZoomButton>
      </div>
      <div className="text-tertiary pointer-events-none absolute right-4 bottom-5 text-xs">
        Drag from an output to connect · Ctrl + scroll to zoom · Delete removes
        the selection
      </div>
    </div>
  )
}

function EdgeRemoveButton({
  graph,
  index,
  onRemove,
  types,
}: {
  graph: WorkflowGraph
  index: number
  onRemove: (index: number) => void
  types: StepTypes
}) {
  const edge = graph.edges[index]
  const a = graph.nodes.find((n) => n.id === edge?.source)
  const b = graph.nodes.find((n) => n.id === edge?.target)
  if (!edge || !a || !b) return null
  const mid = edgePath(outPoint(a, portsOf(a, types), edge.port), inPoint(b))
  return (
    <button
      aria-label="Remove connection"
      className="border-tertiary bg-primary text-danger absolute flex size-6 items-center justify-center rounded-full border"
      onClick={() => onRemove(index)}
      onPointerDown={(e) => e.stopPropagation()}
      style={{ left: mid.x - 12, top: mid.y - 12 }}
      title="Remove connection"
      type="button"
    >
      <X className="size-3" />
    </button>
  )
}

function ZoomButton({
  children,
  label,
  onClick,
}: {
  children: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      aria-label={label}
      className="hover:bg-secondary flex size-8 items-center justify-center"
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  )
}
