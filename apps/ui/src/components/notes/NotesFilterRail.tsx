import { Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import { colorForTag } from './notesHelpers'
import type { TagRef } from '@/types'

interface Props {
  tags: TagRef[]
  counts: Record<string, number>
  active: ReadonlySet<string>
  onToggle: (slug: string) => void
  onClear: () => void
  search: string
  onSearchChange: (value: string) => void
  totalFiltered: number
  highlightedSlugs?: ReadonlySet<string>
  disabled?: boolean
}

export function NotesFilterRail({
  tags,
  counts,
  active,
  onToggle,
  onClear,
  search,
  onSearchChange,
  totalFiltered,
  highlightedSlugs,
  disabled = false,
}: Props) {
  const activeCount = active.size
  return (
    <aside
      className={cn(
        'sticky top-5 self-start',
        disabled && 'pointer-events-none select-none opacity-50',
      )}
      aria-disabled={disabled || undefined}
    >
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary" />
        <Input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search notes"
          className="h-8 pl-8 text-xs"
          disabled={disabled}
          tabIndex={disabled ? -1 : undefined}
        />
      </div>

      {activeCount > 0 && (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-md border border-warning bg-warning px-2.5 py-1.5">
          <span className="text-[11.5px] text-warning">
            {activeCount} filter{activeCount > 1 ? 's' : ''} · {totalFiltered}{' '}
            notes
          </span>
          <button
            type="button"
            onClick={onClear}
            className="cursor-pointer border-0 bg-transparent p-0 text-[11.5px] text-warning hover:underline"
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
                  key={t.slug}
                  tag={t}
                  count={count}
                  active={active.has(t.slug)}
                  highlighted={highlightedSlugs?.has(t.slug)}
                  onClick={() => onToggle(t.slug)}
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
  tag,
  count,
  active,
  highlighted,
  onClick,
}: {
  tag: TagRef
  count: number
  active: boolean
  highlighted?: boolean
  onClick: () => void
}) {
  const hex = colorForTag(tag.slug)
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2 rounded-md border-0 px-2 py-1 text-left transition-colors',
        active ? 'bg-secondary' : 'bg-transparent hover:bg-secondary',
      )}
    >
      <span
        aria-hidden
        className="flex-shrink-0 rounded-sm"
        style={{
          width: 10,
          height: 10,
          backgroundColor: `${hex}55`,
          border: `0.5px solid ${hex}`,
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
