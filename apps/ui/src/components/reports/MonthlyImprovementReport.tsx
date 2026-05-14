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
        <span className="text-secondary text-sm">Month</span>
        <div className="relative">
          <select
            className="border-tertiary bg-primary text-primary hover:border-secondary h-8 appearance-none rounded border py-0 pr-8 pl-3 text-sm transition-colors focus:ring-0 focus:outline-none"
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
          <ChevronDown className="text-tertiary pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2" />
        </div>
      </div>

      {/* Table */}
      <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
        {/* Table header */}
        <div
          className="border-tertiary bg-secondary grid border-b"
          style={COL_GRID}
        >
          <div className="text-primary px-5 py-3 text-[13px] font-medium">
            Team
          </div>
          <div className="text-primary px-5 py-3 text-right text-[13px] font-medium">
            Monthly improvement
          </div>
          <div className="text-primary px-5 py-3 text-right text-[13px] font-medium">
            Stack health score
          </div>
        </div>

        {isLoading ? (
          <div className="text-tertiary py-16 text-center text-sm">
            Loading…
          </div>
        ) : hasError ? (
          <div className="text-danger py-16 text-center text-sm">
            Failed to load report data. Please try again.
          </div>
        ) : sorted.length === 0 ? (
          <div className="text-tertiary py-16 text-center text-sm">
            No score data for {selected.label}.
          </div>
        ) : (
          <>
            {sorted.map((row, i) => (
              <div
                className={`border-tertiary hover:bg-secondary grid items-center transition-colors last:border-0 ${i === sorted.length - 1 ? 'border-0' : 'border-b'}`}
                key={row.key}
                style={COL_GRID}
              >
                <div className="text-primary px-5 py-3.5 text-[13px]">
                  <span className="text-tertiary mr-2 tabular-nums">
                    {i + 1}.
                  </span>
                  {row.name}
                </div>
                <div className="px-5 py-3.5 text-right">
                  <ImprovementPill value={row.improvement} />
                </div>
                <div className="px-5 py-3.5 text-right">
                  {row.current_avg_score != null ? (
                    <ScorePill score={row.current_avg_score} />
                  ) : (
                    <span className="text-tertiary inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums">
                      —
                    </span>
                  )}
                </div>
              </div>
            ))}

            {/* Org-wide summary row */}
            <div
              className="border-tertiary bg-secondary grid items-center border-t"
              style={COL_GRID}
            >
              <div className="text-primary px-5 py-4 text-[13px] font-medium tracking-wide uppercase">
                {orgName} wide
              </div>
              <div className="px-5 py-4 text-right">
                <ImprovementPill value={orgWide.improvement} />
              </div>
              <div className="px-5 py-4 text-right">
                {orgWide.avg_score != null ? (
                  <ScorePill score={orgWide.avg_score} />
                ) : (
                  <span className="text-tertiary inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums">
                    —
                  </span>
                )}
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

function ImprovementPill({ value }: { value: null | number }) {
  if (value == null) {
    return (
      <span className="text-tertiary inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums">
        —
      </span>
    )
  }

  const positive = value > 0
  const zero = value === 0
  const bg = zero
    ? 'var(--background-color-secondary)'
    : positive
      ? 'var(--background-color-success)'
      : 'var(--background-color-danger)'
  const color = zero
    ? 'var(--text-color-secondary)'
    : positive
      ? 'var(--text-color-success)'
      : 'var(--text-color-danger)'

  return (
    <span
      className="inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums"
      style={{ background: bg, color }}
    >
      {positive ? '+' : ''}
      {value.toFixed(2)}
    </span>
  )
}

function scoreBgColor(score: number): string {
  if (score >= 85) return 'var(--background-color-success)'
  if (score >= 70) return 'var(--background-color-warning)'
  return 'var(--background-color-danger)'
}

function scoreColor(score: number): string {
  if (score >= 85) return 'var(--text-color-success)'
  if (score >= 70) return 'var(--text-color-warning)'
  return 'var(--text-color-danger)'
}

function ScorePill({ score }: { score: number }) {
  return (
    <span
      className="inline-flex h-6 items-center rounded px-2 font-mono text-xs font-medium tabular-nums"
      style={{
        background: scoreBgColor(score),
        color: scoreColor(score),
      }}
    >
      {score.toFixed(1)}
    </span>
  )
}
