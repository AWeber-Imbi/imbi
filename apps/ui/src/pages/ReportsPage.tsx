import { useNavigate, useParams } from 'react-router-dom'

import { BarChart3, GitCommitHorizontal, TrendingUp } from 'lucide-react'

import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { MonthlyImprovementReport } from '@/components/reports/MonthlyImprovementReport'
import { ScoreHistoryReport } from '@/components/reports/ScoreHistoryReport'
import { TeamKPIReport } from '@/components/reports/TeamKPIReport'
import { usePageTitle } from '@/hooks/usePageTitle'

interface Report {
  description: string
  id: string
  label: string
  subtitle: string
}

const REPORTS: Report[] = [
  {
    description: 'Month-over-month score delta',
    id: 'monthly-improvement',
    label: 'Monthly improvement',
    subtitle: 'Score improvement by team for a selected month',
  },
  {
    description: 'Score trends over time per team',
    id: 'score-history',
    label: 'Score history',
    subtitle: 'Avg score trend per team over time',
  },
  {
    description: 'Avg quality score per team',
    id: 'team-kpi',
    label: 'Team KPI',
    subtitle: 'Quality score rollup by team',
  },
]

const DEFAULT_REPORT = REPORTS[0].id
const VALID_IDS = new Set(REPORTS.map((r) => r.id))

export function ReportsPage() {
  usePageTitle('Reports')
  const { reportId } = useParams<{ reportId?: string }>()
  const navigate = useNavigate()

  const activeId =
    reportId && VALID_IDS.has(reportId) ? reportId : DEFAULT_REPORT
  const active = REPORTS.find((r) => r.id === activeId) ?? REPORTS[0]

  function selectReport(id: string) {
    navigate(`/reports/${id}`, { replace: true })
  }

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="mx-auto flex max-w-[1400px] gap-6 px-6 py-7">
          {/* Left sidebar — report list */}
          <aside className="w-56 shrink-0">
            <div className="border-tertiary bg-primary rounded-lg border">
              <div className="border-tertiary border-b px-4 py-3">
                <div className="text-overline text-tertiary tracking-wide uppercase">
                  Reports
                </div>
              </div>
              <div className="space-y-1 p-2">
                {REPORTS.map((r) => {
                  const isActive = r.id === activeId
                  return (
                    <button
                      className={`flex w-full items-start gap-3 rounded-lg px-4 py-3 text-left transition-colors ${
                        isActive
                          ? 'bg-warning text-warning'
                          : 'text-secondary hover:bg-secondary hover:text-primary'
                      }`}
                      key={r.id}
                      onClick={() => selectReport(r.id)}
                    >
                      {r.id === 'team-kpi' ? (
                        <BarChart3 className="mt-0.5 size-3.5 shrink-0" />
                      ) : r.id === 'score-history' ? (
                        <GitCommitHorizontal className="mt-0.5 size-3.5 shrink-0" />
                      ) : (
                        <TrendingUp className="mt-0.5 size-3.5 shrink-0" />
                      )}
                      <div>
                        <div className="text-[13px] font-medium">{r.label}</div>
                        <div className="mt-0.5 text-[11px] opacity-70">
                          {r.description}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          </aside>

          {/* Main content */}
          <div className="min-w-0 flex-1">
            <div className="mb-5 flex items-baseline gap-3">
              <h1 className="text-primary text-[18px] font-medium">
                {active.label}
              </h1>
              <span className="text-tertiary text-sm">{active.subtitle}</span>
            </div>
            {activeId === 'team-kpi' && <TeamKPIReport />}
            {activeId === 'monthly-improvement' && <MonthlyImprovementReport />}
            {activeId === 'score-history' && <ScoreHistoryReport />}
          </div>
        </div>
      </main>
      <CommandBar />
    </div>
  )
}
