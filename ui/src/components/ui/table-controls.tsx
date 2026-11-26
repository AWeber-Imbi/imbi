import { type ReactNode, useState } from 'react'

import { ChevronDown, ChevronsUpDown, ChevronUp } from 'lucide-react'

import { FilterPopover } from './filter-popover'

type SortValue = number | string

/** A column header with a filter control after the title. */
export function headerWithFilter(text: ReactNode, control: ReactNode) {
  return (
    <span className="flex items-center gap-1">
      {text}
      {control}
    </span>
  )
}

/**
 * Multi-select facet filters. A row matches a facet when no option is
 * selected, or when one of its values is selected. The options of a
 * facet are the values of `rows`, with their row counts.
 */
export function useTableFacets<K extends string, T>(
  keys: readonly K[],
  values: (row: T, key: K) => string[],
  rows: T[],
) {
  const [facets, setFacets] = useState(
    () =>
      Object.fromEntries(keys.map((k) => [k, [] as string[]])) as Record<
        K,
        string[]
      >,
  )
  const matches = (row: T) =>
    keys.every(
      (k) =>
        facets[k].length === 0 ||
        values(row, k).some((v) => facets[k].includes(v)),
    )
  const facet = (key: K, label: string, labelOf: (slug: string) => string) => {
    const counts = new Map<string, number>()
    for (const row of rows)
      for (const v of new Set(values(row, key)))
        counts.set(v, (counts.get(v) ?? 0) + 1)
    const options = [...counts]
      .map(([slug, count]) => ({ count, label: labelOf(slug), slug }))
      .sort((a, b) => a.label.localeCompare(b.label))
    return (
      <FilterPopover
        activeFilters={new Set(facets[key])}
        label={label}
        onClear={() => setFacets({ ...facets, [key]: [] })}
        onToggle={(slug) =>
          setFacets({
            ...facets,
            [key]: facets[key].includes(slug)
              ? facets[key].filter((s) => s !== slug)
              : [...facets[key], slug],
          })
        }
        options={options}
      />
    )
  }
  return { facet, matches }
}

/** A sort header button and the sort it applies to the rows. */
export function useTableSort<K extends string, T>(
  value: (row: T, key: K) => SortValue,
) {
  const [sort, setSort] = useState<null | { dir: -1 | 1; key: K }>(null)
  const sortButton = (key: K, text: string) => {
    const active = sort?.key === key
    const Icon = !active
      ? ChevronsUpDown
      : sort.dir === 1
        ? ChevronUp
        : ChevronDown
    return (
      <button
        className="hover:text-primary inline-flex items-center gap-1"
        onClick={() =>
          setSort((s) =>
            s?.key === key
              ? { dir: s.dir === 1 ? -1 : 1, key }
              : { dir: 1, key },
          )
        }
        type="button"
      >
        {text}
        {active && (
          <span className="sr-only">
            , sorted {sort.dir === 1 ? 'ascending' : 'descending'}
          </span>
        )}
        <Icon
          className={`size-3.5 shrink-0 ${active ? '' : 'text-tertiary/50'}`}
        />
      </button>
    )
  }
  const sorted = (rows: T[]) =>
    sort
      ? [...rows].sort((a, b) => {
          const x = value(a, sort.key)
          const y = value(b, sort.key)
          return (
            sort.dir *
            (typeof x === 'string' ? x.localeCompare(String(y)) : x - Number(y))
          )
        })
      : rows
  return { sortButton, sorted }
}
