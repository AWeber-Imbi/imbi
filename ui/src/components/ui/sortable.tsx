import type * as React from 'react'
import { useMemo, useState } from 'react'

import { ChevronDown, ChevronsUpDown, ChevronUp } from 'lucide-react'

export type SortDir = 'asc' | 'desc'

export interface SortState<K extends string> {
  ariaSort: (key: K) => 'ascending' | 'descending' | undefined
  dir: SortDir
  key: K | null
  toggle: (key: K) => void
}

type SortValue = Date | null | number | string | undefined

export function SortButton<K extends string>({
  children,
  column,
  sort,
}: {
  children: React.ReactNode
  column: K
  sort: SortState<K>
}) {
  const active = sort.key === column
  const Icon = !active
    ? ChevronsUpDown
    : sort.dir === 'asc'
      ? ChevronUp
      : ChevronDown
  return (
    <button
      className="hover:text-primary inline-flex items-center gap-1"
      onClick={() => sort.toggle(column)}
      type="button"
    >
      {children}
      <Icon className={`size-3 shrink-0${active ? '' : ' text-tertiary/50'}`} />
    </button>
  )
}

/** A ``<th>`` (or a grid header ``<div>``) with a sort button. */
export function SortHeader<K extends string>({
  as: Tag = 'th',
  children,
  className,
  column,
  sort,
}: {
  as?: 'div' | 'th'
  children: React.ReactNode
  className?: string
  column: K
  sort: SortState<K>
}) {
  return (
    <Tag
      aria-sort={sort.ariaSort(column)}
      className={className}
      role={Tag === 'div' ? 'columnheader' : undefined}
    >
      <SortButton column={column} sort={sort}>
        {children}
      </SortButton>
    </Tag>
  )
}

/**
 * Client-side column sort for report tables.
 *
 * ``accessors`` must be stable (module scope or memoized). With no
 * ``initial`` key the rows keep their incoming (server) order until a
 * header is clicked. A first click sorts numbers high-to-low and text
 * A-to-Z; empty values always sort last.
 */
export function useSort<T, K extends string>(
  rows: readonly T[],
  accessors: Record<K, (row: T) => SortValue>,
  initial?: { dir: SortDir; key: NoInfer<K> },
): SortState<K> & { sorted: T[] } {
  const [key, setKey] = useState<K | null>(initial?.key ?? null)
  const [dir, setDir] = useState<SortDir>(initial?.dir ?? 'asc')

  const sorted = useMemo(() => {
    if (key === null) return [...rows]
    const get = accessors[key]
    const sign = dir === 'asc' ? 1 : -1
    // Read each row's value once, not on every comparison.
    return rows
      .map((row) => [get(row), row] as const)
      .sort(([av], [bv]) => {
        if (av == null || av === '') return bv == null || bv === '' ? 0 : 1
        if (bv == null || bv === '') return -1
        return sign * compare(av, bv)
      })
      .map(([, row]) => row)
  }, [rows, accessors, key, dir])

  const toggle = (next: K) => {
    if (next === key) {
      setDir(dir === 'asc' ? 'desc' : 'asc')
      return
    }
    const sample = rows.map(accessors[next]).find((v) => v != null)
    setKey(next)
    setDir(typeof sample === 'string' ? 'asc' : 'desc')
  }

  const ariaSort = (col: K) =>
    col !== key ? undefined : dir === 'asc' ? 'ascending' : 'descending'

  return { ariaSort, dir, key, sorted, toggle }
}

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

function compare(a: Exclude<SortValue, null | undefined>, b: typeof a) {
  if (typeof a === 'string' && typeof b === 'string')
    return collator.compare(a, b)
  return Number(a) - Number(b)
}
