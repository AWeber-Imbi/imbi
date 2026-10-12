import { useState } from 'react'

import { ChevronDown, ChevronRight, PanelLeftClose, Search } from 'lucide-react'

import { cn } from '@/lib/utils'

import { STEP_MIME } from './Canvas'
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CATEGORY_TILE,
  stepIcon,
} from './stepStyle'
import type { StepCategory, StepType } from './types'

/** The step palette: search, collapsible groups, click or drag to add. */
export function Palette({
  onAdd,
  onClose,
  types,
}: {
  onAdd: (type: StepType) => void
  onClose: () => void
  types: StepType[]
}) {
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Set<StepCategory>>(new Set())
  const q = query.trim().toLowerCase()

  return (
    <aside className="border-tertiary bg-primary flex w-62 shrink-0 flex-col border-r">
      <div className="border-tertiary flex items-center gap-2 border-b p-3">
        <div className="relative flex-1">
          <Search className="text-tertiary absolute top-2.25 left-2.25 size-3.5" />
          <input
            aria-label="Search steps"
            className="border-input bg-background focus:border-amber-border h-8 w-full rounded-md border pr-2 pl-7.5 text-sm outline-none"
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search steps"
            value={query}
          />
        </div>
        <button
          aria-label="Hide steps"
          className="text-secondary hover:bg-secondary flex size-8 items-center justify-center rounded-md"
          onClick={onClose}
          title="Hide steps"
          type="button"
        >
          <PanelLeftClose className="size-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-auto p-2 pb-4">
        {CATEGORY_ORDER.map((category) => {
          const items = types.filter(
            (t) =>
              t.category === category &&
              (!q || `${t.label} ${t.description}`.toLowerCase().includes(q)),
          )
          if (items.length === 0) return null
          const open = !!q || !collapsed.has(category)
          const Chevron = open ? ChevronDown : ChevronRight
          return (
            <div className="flex flex-col gap-0.5" key={category}>
              <button
                aria-expanded={open}
                className="text-overline text-tertiary hover:text-primary flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left uppercase"
                onClick={() => {
                  const next = new Set(collapsed)
                  if (next.has(category)) next.delete(category)
                  else next.add(category)
                  setCollapsed(next)
                }}
                type="button"
              >
                <span className="flex-1">{CATEGORY_LABEL[category]}</span>
                <span className="font-mono normal-case">{items.length}</span>
                <Chevron className="size-3.5" />
              </button>
              {open &&
                items.map((t) => {
                  const Icon = stepIcon(t.type, t.category)
                  return (
                    <button
                      className="hover:bg-secondary flex cursor-grab items-center gap-2.5 rounded-md px-2 py-1.5 text-left"
                      draggable
                      key={t.type}
                      onClick={() => onAdd(t)}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(STEP_MIME, t.type)
                        e.dataTransfer.effectAllowed = 'copy'
                      }}
                      title="Click to add, or drag onto the canvas"
                      type="button"
                    >
                      <span
                        className={cn(
                          'flex size-7 shrink-0 items-center justify-center rounded-md',
                          CATEGORY_TILE[t.category],
                        )}
                      >
                        <Icon className="size-3.5" />
                      </span>
                      <span className="flex min-w-0 flex-col">
                        <span className="text-sm font-medium">{t.label}</span>
                        <span className="text-tertiary truncate text-xs">
                          {t.description}
                        </span>
                      </span>
                    </button>
                  )
                })}
            </div>
          )
        })}
      </div>
    </aside>
  )
}
