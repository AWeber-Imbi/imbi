import { useState } from 'react'

import { ChevronDown, Search, SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { TagRef } from '@/types'

import { colorForTag } from './documentsHelpers'

interface Props {
  active: ReadonlySet<string>
  counts: Record<string, number>
  disabled?: boolean
  highlightedSlugs?: ReadonlySet<string>
  onClear: () => void
  onSearchChange: (value: string) => void
  onToggle: (slug: string) => void
  search: string
  tags: TagRef[]
  totalFiltered: number
}

export function DocumentsFilterRail({
  active,
  counts,
  disabled = false,
  highlightedSlugs,
  onClear,
  onSearchChange,
  onToggle,
  search,
  tags,
  totalFiltered,
}: Props) {
  const activeCount = active.size
  // Below `lg` the rail sits above content as a bar; tags collapse behind a
  // "Filters" disclosure so they don't push the content down. At `lg`+ it is
  // the sticky sidebar and tags are always shown.
  const [open, setOpen] = useState(false)
  return (
    <aside
      aria-disabled={disabled || undefined}
      className={cn(
        'lg:sticky lg:top-5 lg:self-start',
        disabled && 'pointer-events-none opacity-50 select-none',
      )}
    >
      <div className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="text-tertiary pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <Input
            className="h-8 pl-8 text-xs"
            disabled={disabled}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search documents"
            tabIndex={disabled ? -1 : undefined}
            value={search}
          />
        </div>
        {tags.length > 0 && (
          <Button
            aria-expanded={open}
            className="shrink-0 gap-1.5 lg:hidden"
            disabled={disabled}
            onClick={() => setOpen((o) => !o)}
            size="sm"
            tabIndex={disabled ? -1 : undefined}
            variant="outline"
          >
            <SlidersHorizontal className="size-3.5" />
            Filters
            {activeCount > 0 && (
              <span className="text-tertiary tabular-nums">{activeCount}</span>
            )}
            <ChevronDown
              className={cn(
                'size-3 transition-transform',
                open && 'rotate-180',
              )}
            />
          </Button>
        )}
      </div>

      {activeCount > 0 && (
        <div className="border-warning bg-warning mb-3 flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5">
          <span className="text-warning text-[11.5px]">
            {activeCount} filter{activeCount > 1 ? 's' : ''} · {totalFiltered}{' '}
            documents
          </span>
          <Button
            className="text-warning text-[11.5px]"
            onClick={onClear}
            size="sm"
            variant="link"
          >
            Clear
          </Button>
        </div>
      )}

      {tags.length > 0 && (
        <div className={cn(open ? 'block' : 'hidden', 'lg:block')}>
          <div className="text-overline text-tertiary mb-1.5 uppercase">
            Tags
          </div>
          <div className="flex flex-wrap gap-1.5 lg:flex-col lg:flex-nowrap lg:gap-0.5">
            {tags.map((t) => {
              const count = counts[t.slug] ?? 0
              if (!count) return null
              return (
                <TagButton
                  active={active.has(t.slug)}
                  count={count}
                  highlighted={highlightedSlugs?.has(t.slug)}
                  key={t.slug}
                  onClick={() => onToggle(t.slug)}
                  tag={t}
                />
              )
            })}
          </div>
        </div>
      )}
    </aside>
  )
}

function TagButton({
  active,
  count,
  highlighted,
  onClick,
  tag,
}: {
  active: boolean
  count: number
  highlighted?: boolean
  onClick: () => void
  tag: TagRef
}) {
  const hex = colorForTag(tag.slug)
  return (
    <button
      className={cn(
        'flex w-auto items-center gap-2 rounded-md border-0 px-2 py-1 text-left transition-colors lg:w-full',
        active ? 'bg-secondary' : 'bg-transparent hover:bg-secondary',
      )}
      onClick={onClick}
      type="button"
    >
      <span
        aria-hidden
        className="shrink-0 rounded-sm"
        style={{
          backgroundColor: `${hex}55`,
          border: `0.5px solid ${hex}`,
          height: 10,
          width: 10,
        }}
      />
      <span
        className={cn(
          'truncate text-[12.5px] lg:flex-1',
          active || highlighted ? 'font-medium text-primary' : 'text-secondary',
        )}
      >
        {tag.name}
      </span>
      <span className="text-tertiary font-mono text-[11px]">{count}</span>
    </button>
  )
}
