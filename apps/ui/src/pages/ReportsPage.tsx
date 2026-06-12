import { useEffect } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  BarChart3,
  GitCommitHorizontal,
  GitPullRequest,
  Network,
  TrendingUp,
} from 'lucide-react'

import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { MonthlyImprovementReport } from '@/components/reports/MonthlyImprovementReport'
import { OpenPullRequestsReport } from '@/components/reports/OpenPullRequestsReport'
import { ProjectsGraphReport } from '@/components/reports/ProjectsGraphReport'
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
    label: 'Monthly Improvement',
    subtitle: 'Score improvement by team for a selected month',
  },
  {
    description: 'Open pull requests across the org',
    id: 'open-pull-requests',
    label: 'Open Pull Requests',
    subtitle: 'Open pull requests, filterable by team and project type',
  },
  {
    description: 'Service dependency graph',
    id: 'projects-graph',
    label: 'Projects Graph',
    subtitle: 'Project relationships across the org',
  },
  {
    description: 'Score trends over time per team',
    id: 'score-history',
    label: 'Score History',
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

// fallow-ignore-next-line complexity
export function ReportsPage() {
  usePageTitle('Reports')
  const { reportId } = useParams<{ reportId?: string }>()
  const navigate = useNavigate()

  const activeId =
    reportId && VALID_IDS.has(reportId) ? reportId : DEFAULT_REPORT
  const active = REPORTS.find((r) => r.id === activeId) ?? REPORTS[0]

  // Canonicalize bare /reports (and unknown ids) to an explicit report URL
  useEffect(() => {
    if (reportId !== activeId) {
      navigate(`/reports/${activeId}`, { replace: true })
    }
  }, [reportId, activeId, navigate])

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="mx-auto flex max-w-screen-2xl gap-6 px-6 py-7">
          {/* Left sidebar — report list */}
          <aside className="w-56 shrink-0">
            <div className="border-tertiary bg-primary rounded-lg border">
              <div className="border-tertiary border-b px-4 py-3">
                <div className="text-overline text-tertiary tracking-wide uppercase">
                  Reports
                </div>
              </div>
              <div className="space-y-1 p-2">
                {/* fallow-ignore-next-line complexity */}
                {REPORTS.map((r) => {
                  const isActive = r.id === activeId
                  return (
                    <Link
                      className={`flex w-full items-start gap-3 rounded-lg px-4 py-3 text-left transition-colors ${
                        isActive
                          ? 'bg-warning text-warning'
                          : 'text-secondary hover:bg-secondary hover:text-primary'
                      }`}
                      key={r.id}
                      to={`/reports/${r.id}`}
                    >
                      {r.id === 'team-kpi' ? (
                        <BarChart3 className="mt-0.5 size-3.5 shrink-0" />
                      ) : r.id === 'score-history' ? (
                        <GitCommitHorizontal className="mt-0.5 size-3.5 shrink-0" />
                      ) : r.id === 'projects-graph' ? (
                        <Network className="mt-0.5 size-3.5 shrink-0" />
                      ) : r.id === 'open-pull-requests' ? (
                        <GitPullRequest className="mt-0.5 size-3.5 shrink-0" />
                      ) : (
                        <TrendingUp className="mt-0.5 size-3.5 shrink-0" />
                      )}
                      <div>
                        <div className="text-[13px] font-medium">{r.label}</div>
                        <div className="mt-0.5 text-[11px] opacity-70">
                          {r.description}
                        </div>
                      </div>
                    </Link>
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
            {activeId === 'open-pull-requests' && <OpenPullRequestsReport />}
            {activeId === 'score-history' && <ScoreHistoryReport />}
            {activeId === 'projects-graph' && <ProjectsGraphReport />}
          </div>
        </div>
      </main>
      <CommandBar />
    </div>
  )
}
