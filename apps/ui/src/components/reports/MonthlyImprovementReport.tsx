import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'

import {
  getMonthlyImprovement,
  listTeams,
  MonthlyImprovementRow,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { Team } from '@/types'

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

interface MonthOption {
  label: string
  month: number
  year: number
}

interface TeamRow extends MonthlyImprovementRow {
  name: string
}

export function MonthlyImprovementReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const orgName = selectedOrganization?.name ?? 'Org'

  const monthOptions = useMemo<MonthOption[]>(() => {
    const opts: MonthOption[] = []
    const now = new Date()
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
      opts.push({
        label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`,
        month: d.getMonth() + 1,
        year: d.getFullYear(),
      })
    }
    return opts
  }, [])

  const [selected, setSelected] = useState<MonthOption>(monthOptions[0])

  const {
    data: rawRows,
    error: rowsError,
    isLoading: rowsLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getMonthlyImprovement(
        { month: selected.month, year: selected.year },
        signal,
      ),
    queryKey: ['monthlyImprovement', orgSlug, selected.year, selected.month],
    staleTime: 120_000,
  })

  const {
    data: teams,
    error: teamsError,
    isLoading: teamsLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
    staleTime: 120_000,
  })

  const isLoading = rowsLoading || teamsLoading
  const hasError = !!(rowsError || teamsError)

  const rows: TeamRow[] = useMemo(() => {
    if (!rawRows) return []
    const teamBySlug = new Map<string, Team>(
      (teams ?? []).map((t) => [t.slug, t]),
    )
    return rawRows.map((r) => ({
      ...r,
      name: teamBySlug.get(r.key)?.name ?? r.key,
    }))
  }, [rawRows, teams])

  // Sort: descending improvement, nulls last
  const sorted = useMemo(
    () =>
      [...rows].sort((a, b) => {
        if (a.improvement == null && b.improvement == null) return 0
        if (a.improvement == null) return 1
        if (b.improvement == null) return -1
        return b.improvement - a.improvement
      }),
    [rows],
  )

  // Org-wide aggregates (project_count-weighted)
  const orgWide = useMemo(() => {
    const withCur = rows.filter(
      (r) => r.current_avg_score != null && r.project_count > 0,
    )
    const withImp = rows.filter(
      (r) => r.improvement != null && r.project_count > 0,
    )
    const totalCurWeight = withCur.reduce((s, r) => s + r.project_count, 0)
    const totalImpWeight = withImp.reduce((s, r) => s + r.project_count, 0)
    return {
      avg_score:
        totalCurWeight > 0
          ? withCur.reduce(
              (s, r) => s + r.current_avg_score! * r.project_count,
              0,
            ) / totalCurWeight
          : null,
      improvement:
        totalImpWeight > 0
          ? withImp.reduce((s, r) => s + r.improvement! * r.project_count, 0) /
            totalImpWeight
          : null,
    }
  }, [rows])

  return (
    <div className="flex flex-col gap-5">
      {/* Month selector */}
      <div className="flex items-center gap-3">
        <span className="text-sm text-secondary">Month</span>
        <div className="relative">
          <select
            className="h-8 appearance-none rounded border border-tertiary bg-primary py-0 pl-3 pr-8 text-sm text-primary transition-colors hover:border-secondary focus:outline-none focus:ring-0"
            onChange={(e) => {
              const opt = monthOptions[Number(e.target.value)]
              if (opt) setSelected(opt)
            }}
            value={monthOptions.indexOf(selected)}
          >
            {monthOptions.map((opt, i) => (
              <option key={`${opt.year}-${opt.month}`} value={i}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary" />
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-tertiary bg-primary">
        {/* Table header */}
        <div
          className="grid border-b border-tertiary bg-secondary"
          style={COL_GRID}
        >
          <div className="px-5 py-3 text-[13px] font-medium text-primary">
            Team
          </div>
          <div className="px-5 py-3 text-right text-[13px] font-medium text-primary">
            Monthly improvement
          </div>
          <div className="px-5 py-3 text-right text-[13px] font-medium text-primary">
            Stack health score
          </div>
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-sm text-tertiary">
            Loading…
          </div>
        ) : hasError ? (
          <div className="py-16 text-center text-sm text-danger">
            Failed to load report data. Please try again.
          </div>
        ) : sorted.length === 0 ? (
          <div className="py-16 text-center text-sm text-tertiary">
            No score data for {selected.label}.
          </div>
        ) : (
          <>
            {sorted.map((row, i) => (
              <div
                className="grid items-center border-b border-tertiary transition-colors last:border-0 hover:bg-secondary"
                key={row.key}
                style={COL_GRID}
              >
                <div className="px-5 py-3.5 text-[13px] text-primary">
                  <span className="mr-2 tabular-nums text-tertiary">
                    {i + 1}.
                  </span>
                  {row.name}
                </div>
                <div className="px-5 py-3.5 text-right">
                  <ImprovementValue value={row.improvement} />
                </div>
                <div className="px-5 py-3.5 text-right font-mono text-[13px] tabular-nums text-primary">
                  {row.current_avg_score != null
                    ? `${row.current_avg_score.toFixed(2)}%`
                    : '—'}
                </div>
              </div>
            ))}

            {/* Org-wide summary row */}
            <div
              className="grid items-center border-t border-tertiary bg-secondary"
              style={COL_GRID}
            >
              <div className="px-5 py-4 text-[13px] font-medium uppercase tracking-wide text-primary">
                {orgName} wide
              </div>
              <div className="px-5 py-4 text-right">
                <ImprovementValue bold value={orgWide.improvement} />
              </div>
              <div className="px-5 py-4 text-right font-mono text-[13px] font-medium tabular-nums text-primary">
                {orgWide.avg_score != null
                  ? `${orgWide.avg_score.toFixed(2)}%`
                  : '—'}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const COL_GRID = {
  gridTemplateColumns: '1fr 220px 220px',
}

function ImprovementValue({
  bold = false,
  value,
}: {
  bold?: boolean
  value: null | number
}) {
  if (value == null) {
    return (
      <span className="font-mono text-[13px] tabular-nums text-tertiary">
        —
      </span>
    )
  }

  const positive = value > 0
  const zero = value === 0
  const color = zero
    ? 'var(--color-text-secondary)'
    : positive
      ? 'var(--color-text-success)'
      : 'var(--color-text-danger)'

  return (
    <span
      className={`font-mono text-[13px] tabular-nums ${bold ? 'font-medium' : ''}`}
      style={{ color }}
    >
      {positive ? '+' : ''}
      {value.toFixed(2)}
    </span>
  )
}
