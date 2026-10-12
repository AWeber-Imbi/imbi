import type { PointerEvent } from 'react'

import { cn } from '@/lib/utils'

import { isSinglePort, NODE_W } from './graph'
import { CATEGORY_TILE, stepIcon } from './stepStyle'
import type { StepType, WorkflowNode } from './types'

export interface NodeSummary {
  text: string
  tone: 'danger' | 'normal' | 'warning'
}

interface CanvasNodeProps {
  node: WorkflowNode
  onPointerDown: (e: PointerEvent) => void
  onPortDown: (e: PointerEvent, port: number) => void
  ports: string[]
  selected: boolean
  summary: NodeSummary
  type: StepType | undefined
  usedPorts: Set<number>
}

const SUMMARY_TONE = {
  danger: 'text-danger',
  normal: 'text-secondary',
  warning: 'text-amber-text',
}

export function CanvasNode({
  node,
  onPointerDown,
  onPortDown,
  ports,
  selected,
  summary,
  type,
  usedPorts,
}: CanvasNodeProps) {
  const Icon = stepIcon(node.type, type?.category)
  const single = isSinglePort(ports)
  const port = (i: number, className: string) => (
    <div
      aria-label={ports[i] ? `Connect from ${ports[i]}` : 'Connect'}
      className={cn(
        'border-primary hover:border-amber-border hover:bg-amber-border absolute -right-2 size-4 cursor-crosshair rounded-full border-2 transition-colors',
        usedPorts.has(i) ? 'bg-tertiary' : 'bg-primary',
        className,
      )}
      data-port={i}
      onPointerDown={(e) => onPortDown(e, i)}
      title="Drag to connect"
    />
  )
  return (
    <div
      className={cn(
        'bg-primary absolute cursor-grab rounded-lg border select-none',
        selected
          ? 'border-amber-border ring-2 ring-amber-border'
          : summary.tone === 'danger'
            ? 'border-danger'
            : 'border-secondary',
      )}
      data-node-id={node.id}
      onPointerDown={onPointerDown}
      style={{ left: node.position.x, top: node.position.y, width: NODE_W }}
    >
      {!type?.trigger && (
        <div className="border-primary bg-primary absolute top-5.25 -left-1.75 size-3.5 rounded-full border-2" />
      )}
      <div className="flex h-14 items-center gap-2.5 px-3">
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-md',
            CATEGORY_TILE[type?.category ?? 'logic'],
          )}
        >
          <Icon className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{node.title}</span>
          <span className="text-tertiary text-xs">
            {type?.label ?? `Unknown type: ${node.type}`}
          </span>
        </div>
      </div>
      <div
        className={cn(
          'h-9 truncate px-3 text-xs leading-4.5',
          SUMMARY_TONE[summary.tone],
        )}
      >
        {summary.text}
      </div>
      {single && port(0, 'top-5')}
      {!single && ports.length > 0 && (
        <div className="border-tertiary border-t py-1">
          {ports.map((label, i) => (
            <div
              className="text-secondary relative flex h-7.5 items-center justify-end pr-4 text-xs font-medium"
              key={i}
            >
              {label}
              {port(i, 'top-1.75')}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
