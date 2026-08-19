import { ChevronDown, ListFilter } from 'lucide-react'

import { Checkbox } from './checkbox'
import { Label } from './label'
import { Popover, PopoverContent, PopoverTrigger } from './popover'

export interface FilterOption {
  /** Rows this option would match given the other active filters. */
  count?: number
  dotClass?: string
  label: string
  slug: string
}

export interface FilterPopoverProps {
  activeFilters: Set<string>
  label: string
  /** Offered in the popover header once anything is selected. */
  onClear?: () => void
  onToggle: (slug: string) => void
  options: FilterOption[]
  /**
   * `icon` is the funnel that lives inside a table header. `button`
   * is the standalone pill for a filter bar above the table, where
   * the facet's name has to be readable without opening it.
   */
  variant?: 'button' | 'icon'
}

/**
 * Multi-select facet filter: a funnel button carrying the active count,
 * opening a checkbox list with per-option match counts.
 *
 * Options with a zero count stay listed but dim — knowing a facet exists
 * and currently matches nothing is more useful than it vanishing.
 */
// fallow-ignore-next-line complexity
export function FilterPopover({
  activeFilters,
  label,
  onClear,
  onToggle,
  options,
  variant = 'icon',
}: FilterPopoverProps) {
  const active = activeFilters.size > 0
  return (
    <Popover>
      <PopoverTrigger asChild>
        {variant === 'button' ? (
          <button
            aria-label={`Filter by ${label}`}
            className={`border-tertiary flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs ${
              active
                ? 'border-action text-action bg-warning'
                : 'bg-primary text-primary hover:border-secondary'
            }`}
            type="button"
          >
            <ListFilter className="size-3.5" />
            {label}
            {active && (
              <span className="bg-action inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 font-mono text-[10px] text-white">
                {activeFilters.size}
              </span>
            )}
            <ChevronDown className="size-3.5" />
          </button>
        ) : (
          <button
            aria-label={`Filter by ${label}`}
            className={`flex items-center gap-0.5 rounded px-0.5 py-0.5 ${
              active ? 'text-action' : 'text-tertiary/50 hover:text-secondary'
            }`}
            type="button"
          >
            <ListFilter className="size-3.5" />
            {active && (
              <span className="text-xs leading-none">{activeFilters.size}</span>
            )}
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-48 p-2">
        <div className="mb-2 flex items-center justify-between gap-2 px-1">
          <p className="text-secondary text-xs font-medium tracking-wide uppercase">
            Filter by {label}
          </p>
          {onClear && active && (
            <button
              className="text-action text-xs"
              onClick={onClear}
              type="button"
            >
              Clear
            </button>
          )}
        </div>
        <div className="max-h-56 space-y-0.5 overflow-y-auto">
          {options.map((opt) => (
            <Label
              className="hover:bg-secondary flex cursor-pointer items-center gap-2 rounded px-1 py-1.5"
              key={opt.slug}
            >
              <Checkbox
                checked={activeFilters.has(opt.slug)}
                onCheckedChange={() => onToggle(opt.slug)}
              />
              {opt.dotClass && (
                <span
                  className={`size-2 shrink-0 rounded-full ${opt.dotClass}`}
                />
              )}
              <span
                className={`text-primary min-w-0 flex-1 truncate text-sm ${
                  opt.count === 0 ? 'opacity-50' : ''
                }`}
              >
                {opt.label}
              </span>
              {opt.count !== undefined && (
                <span
                  className="text-tertiary shrink-0 font-mono text-xs tabular-nums"
                  data-testid="filter-option-count"
                >
                  {opt.count}
                </span>
              )}
            </Label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
