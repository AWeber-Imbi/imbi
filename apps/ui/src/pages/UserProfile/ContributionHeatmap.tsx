import { useMemo } from 'react'

import type { ContributionsResponse } from './api'

interface HeatmapProps {
  data: ContributionsResponse | undefined
  isLoading?: boolean
}

const CELL_SIZE = 11
const CELL_GAP = 2
const WEEKS = 53

const BUCKET_COLORS = [
  'fill-neutral-200 dark:fill-neutral-800',
  'fill-green-200 dark:fill-green-900',
  'fill-green-400 dark:fill-green-700',
  'fill-green-600 dark:fill-green-500',
  'fill-green-800 dark:fill-green-300',
]

export function ContributionHeatmap({ data, isLoading }: HeatmapProps) {
  const cells = useMemo(() => {
    const counts = new Map<string, number>()
    if (data) {
      for (const bucket of data.buckets) {
        counts.set(bucket.date, bucket.count)
      }
    }
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const weekStart = startOfWeek(today)
    const grid: { count: number; date: string; x: number; y: number }[] = []
    for (let w = 0; w < WEEKS; w += 1) {
      const weekIndex = WEEKS - 1 - w
      for (let day = 0; day < 7; day += 1) {
        const d = new Date(weekStart)
        d.setDate(d.getDate() - 7 * w + day)
        if (d > today) continue
        const key = fmtDate(d)
        grid.push({
          count: counts.get(key) ?? 0,
          date: key,
          x: weekIndex,
          y: day,
        })
      }
    }
    return grid
  }, [data])

  const total = data?.total ?? 0
  const width = WEEKS * (CELL_SIZE + CELL_GAP)
  const height = 7 * (CELL_SIZE + CELL_GAP)

  return (
    <section className="rounded-md border border-tertiary bg-primary p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-primary">
          {isLoading
            ? 'Loading contributions…'
            : `${total.toLocaleString()} contributions in the last year`}
        </h2>
        <Legend />
      </header>
      <div className="overflow-x-auto">
        <svg
          aria-label="Contribution heatmap"
          height={height}
          role="img"
          width={width}
        >
          {cells.map((cell) => (
            <rect
              className={BUCKET_COLORS[bucketIndex(cell.count)]}
              height={CELL_SIZE}
              key={`${cell.x}-${cell.y}`}
              rx={2}
              ry={2}
              width={CELL_SIZE}
              x={cell.x * (CELL_SIZE + CELL_GAP)}
              y={cell.y * (CELL_SIZE + CELL_GAP)}
            >
              <title>
                {cell.count} contribution{cell.count === 1 ? '' : 's'} on{' '}
                {cell.date}
              </title>
            </rect>
          ))}
        </svg>
      </div>
    </section>
  )
}

function bucketIndex(count: number): number {
  if (count <= 0) return 0
  if (count < 2) return 1
  if (count < 5) return 2
  if (count < 10) return 3
  return 4
}

function fmtDate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function Legend() {
  return (
    <div className="flex items-center gap-1 text-xs text-tertiary">
      <span>Less</span>
      {BUCKET_COLORS.map((cls, i) => (
        <span
          className={`inline-block h-2.5 w-2.5 rounded-sm ${cls.replace(/fill-/g, 'bg-')}`}
          key={i}
        />
      ))}
      <span>More</span>
    </div>
  )
}

function startOfWeek(date: Date): Date {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  // Reduce to Monday (ISO start of week per design.md mockup)
  const day = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - day)
  return d
}
