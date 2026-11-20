import { type DragEvent, useRef, useState } from 'react'

import {
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
} from 'lucide-react'

import { useResizableWidth } from '@/components/agents/useResizableWidth'
import { useStoredState } from '@/components/agents/useStoredState'
import { cn } from '@/lib/utils'

import { STEP_MIME } from './Canvas'
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CATEGORY_TILE,
  stepIcon,
} from './stepStyle'
import type { StepCategory, StepType } from './types'

/**
 * The step palette: search, collapsible groups, click or drag to add.
 * Collapsed, it is a rail of step icons, which also click or drag to add.
 */
export function Palette({
  onAdd,
  types,
}: {
  onAdd: (type: StepType) => void
  types: StepType[]
}) {
  const [rail, setRail] = useStoredState(
    'imbi:workflows:palette-collapsed',
    false,
    (raw) => (typeof raw === 'boolean' ? raw : undefined),
  )
  // Each presentation has its own toggle, so the focused one unmounts:
  // focus the new one after a toggle, but not on the first render.
  const toggled = useRef(false)
  const toggle = (next: boolean) => {
    toggled.current = true
    setRail(next)
  }
  const toggleRef = (el: HTMLButtonElement | null) => {
    if (el && toggled.current) {
      toggled.current = false
      el.focus()
    }
  }
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Set<StepCategory>>(new Set())
  const q = query.trim().toLowerCase()
  const { handleProps, width } = useResizableWidth(
    'imbi:workflows:palette-width',
    248,
    200,
    480,
  )
  const addProps = (t: StepType) => ({
    draggable: true,
    onClick: () => onAdd(t),
    onDragStart: (e: DragEvent) => {
      e.dataTransfer.setData(STEP_MIME, t.type)
      e.dataTransfer.effectAllowed = 'copy'
    },
    type: 'button' as const,
  })
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: types.filter((t) => t.category === category),
  })).filter((group) => group.items.length > 0)

  if (rail) {
    return (
      <aside className="border-tertiary bg-primary flex w-13 shrink-0 flex-col items-center gap-2 overflow-y-auto border-r py-3">
        <button
          aria-label="Expand steps"
          className="text-secondary hover:bg-secondary flex size-8 shrink-0 items-center justify-center rounded-md"
          onClick={() => toggle(false)}
          ref={toggleRef}
          title="Expand steps"
          type="button"
        >
          <PanelLeftOpen className="size-4" />
        </button>
        {groups.map(({ category, items }) => (
          <div
            className="border-tertiary flex flex-col items-center gap-1 border-t pt-2"
            key={category}
          >
            {items.map((t) => (
              <button
                aria-label={t.label}
                className="hover:bg-secondary cursor-grab rounded-md p-0.5"
                key={t.type}
                title={t.label}
                {...addProps(t)}
              >
                <StepTile type={t} />
              </button>
            ))}
          </div>
        ))}
      </aside>
    )
  }

  return (
    <aside
      className="border-tertiary bg-primary relative flex shrink-0 flex-col border-r"
      style={{ width }}
    >
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
          aria-label="Collapse steps"
          className="text-secondary hover:bg-secondary flex size-8 items-center justify-center rounded-md"
          onClick={() => toggle(true)}
          ref={toggleRef}
          title="Collapse steps"
          type="button"
        >
          <PanelLeftClose className="size-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-auto p-2 pb-4">
        {groups.map(({ category, items: all }) => {
          const items = all.filter(
            (t) =>
              !q || `${t.label} ${t.description}`.toLowerCase().includes(q),
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
                items.map((t) => (
                  <button
                    className="hover:bg-secondary flex cursor-grab items-center gap-2.5 rounded-md px-2 py-1.5 text-left"
                    key={t.type}
                    title="Click to add, or drag onto the canvas"
                    {...addProps(t)}
                  >
                    <StepTile type={t} />
                    <span className="flex min-w-0 flex-col">
                      <span className="text-sm font-medium">{t.label}</span>
                      <span className="text-tertiary truncate text-xs">
                        {t.description}
                      </span>
                    </span>
                  </button>
                ))}
            </div>
          )
        })}
      </div>
      <div {...handleProps} />
    </aside>
  )
}

/** The icon of a step type, on the tile of its category. */
function StepTile({ type }: { type: StepType }) {
  const Icon = stepIcon(type.type)
  return (
    <span
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-md',
        CATEGORY_TILE[type.category],
      )}
    >
      <Icon className="size-3.5" />
    </span>
  )
}
