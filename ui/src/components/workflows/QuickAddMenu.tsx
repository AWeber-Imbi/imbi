import { useState } from 'react'

import { cn } from '@/lib/utils'

import type { Point } from './graph'
import { CATEGORY_LABEL, CATEGORY_TILE, stepIcon } from './stepStyle'
import type { StepType } from './types'

/** The menu that opens when a connection is dropped on empty canvas. */
export function QuickAddMenu({
  at,
  onPick,
  types,
}: {
  at: Point
  onPick: (type: StepType) => void
  types: StepType[]
}) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = types.filter(
    (t) =>
      !q ||
      `${t.label} ${t.description} ${t.category}`.toLowerCase().includes(q),
  )
  return (
    <div
      className="border-tertiary bg-primary absolute z-10 flex w-70 flex-col overflow-hidden rounded-lg border"
      onPointerDown={(e) => e.stopPropagation()}
      style={{ left: at.x, top: at.y }}
    >
      <div className="border-tertiary border-b p-2">
        <input
          aria-label="Search steps"
          autoFocus
          className="border-input bg-background focus:border-amber-border h-8 w-full rounded-md border px-2 text-sm outline-none"
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Add a step after this output"
          value={query}
        />
      </div>
      <div className="max-h-75 overflow-auto p-1">
        {shown.map((t) => {
          const Icon = stepIcon(t.type, t.category)
          return (
            <button
              className="hover:bg-secondary flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left"
              key={t.type}
              onClick={() => onPick(t)}
              type="button"
            >
              <span
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-md',
                  CATEGORY_TILE[t.category],
                )}
              >
                <Icon className="size-3.5" />
              </span>
              <span className="flex-1 text-sm">{t.label}</span>
              <span className="text-tertiary text-xs">
                {CATEGORY_LABEL[t.category]}
              </span>
            </button>
          )
        })}
        {shown.length === 0 && (
          <div className="text-tertiary p-3 text-center text-sm">
            No step matches that search.
          </div>
        )}
      </div>
    </div>
  )
}
