import { Search } from 'lucide-react'

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
  return (
    <aside
      aria-disabled={disabled || undefined}
      className={cn(
        'sticky top-5 self-start',
        disabled && 'pointer-events-none select-none opacity-50',
      )}
    >
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary" />
        <Input
          className="h-8 pl-8 text-xs"
          disabled={disabled}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search documents"
          tabIndex={disabled ? -1 : undefined}
          value={search}
        />
      </div>

      {activeCount > 0 && (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-md border border-warning bg-warning px-2.5 py-1.5">
          <span className="text-[11.5px] text-warning">
            {activeCount} filter{activeCount > 1 ? 's' : ''} · {totalFiltered}{' '}
            documents
          </span>
          <button
            className="cursor-pointer border-0 bg-transparent p-0 text-[11.5px] text-warning hover:underline"
            onClick={onClear}
            type="button"
          >
            Clear
          </button>
        </div>
      )}

      {tags.length > 0 && (
        <div>
          <div className="mb-1.5 text-overline uppercase text-tertiary">
            Tags
          </div>
          <div className="flex flex-col gap-0.5">
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
        'flex w-full items-center gap-2 rounded-md border-0 px-2 py-1 text-left transition-colors',
        active ? 'bg-secondary' : 'bg-transparent hover:bg-secondary',
      )}
      onClick={onClick}
      type="button"
    >
      <span
        aria-hidden
        className="flex-shrink-0 rounded-sm"
        style={{
          backgroundColor: `${hex}55`,
          border: `0.5px solid ${hex}`,
          height: 10,
          width: 10,
        }}
      />
      <span
        className={cn(
          'flex-1 truncate text-[12.5px]',
          active || highlighted ? 'font-medium text-primary' : 'text-secondary',
        )}
      >
        {tag.name}
      </span>
      <span className="font-mono text-[11px] text-tertiary">{count}</span>
    </button>
  )
}
