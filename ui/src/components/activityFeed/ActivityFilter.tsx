/* eslint-disable react-refresh/only-export-components */
import { Filter } from 'lucide-react'

import { Checkbox } from '@/components/ui/checkbox'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import type { ActivityFeedEntry } from '@/types'

import { entryIsBot } from './entryAdapters'

export interface ActivityFilterValue {
  bots: boolean
  people: boolean
}

export const ALL_ACTORS: ActivityFilterValue = { bots: true, people: true }

interface ActivityFilterProps {
  onChange: (value: ActivityFilterValue) => void
  value: ActivityFilterValue
}

/** Funnel button + popover matching the mockup's "Filter" control. */
export function ActivityFilter({ onChange, value }: ActivityFilterProps) {
  const active = !(value.bots && value.people)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="text-secondary hover:bg-secondary relative inline-flex h-7.5 items-center gap-1.5 rounded-md px-2.5 text-[13px] transition-colors"
          type="button"
        >
          <Filter className="size-3.5" />
          Filter
          {active && (
            <span
              className="size-1.5 rounded-full"
              style={{ background: 'var(--ds-action-bg)' }}
            />
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-44 p-2">
        <p className="text-tertiary px-1 pb-1.5 text-[11px] font-semibold tracking-wider uppercase">
          Show
        </p>
        <FilterRow
          checked={value.people}
          label="People"
          onToggle={(v) => onChange({ ...value, people: v })}
        />
        <FilterRow
          checked={value.bots}
          label="Bots"
          onToggle={(v) => onChange({ ...value, bots: v })}
        />
      </PopoverContent>
    </Popover>
  )
}

/** Filter already-loaded entries by actor kind (client-side only). */
export function filterEntries(
  entries: ActivityFeedEntry[],
  value: ActivityFilterValue,
): ActivityFeedEntry[] {
  if (value.bots && value.people) return entries
  return entries.filter((entry) =>
    entryIsBot(entry) ? value.bots : value.people,
  )
}

function FilterRow({
  checked,
  label,
  onToggle,
}: {
  checked: boolean
  label: string
  onToggle: (value: boolean) => void
}) {
  return (
    <label className="hover:bg-secondary flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-sm">
      <Checkbox
        checked={checked}
        onCheckedChange={(state) => onToggle(state === true)}
      />
      {label}
    </label>
  )
}
