import { useState } from 'react'

import { BarChart3, TrendingUp } from 'lucide-react'

import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { MonthlyImprovementReport } from '@/components/reports/MonthlyImprovementReport'
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
    description: 'Avg quality score per team',
    id: 'team-kpi',
    label: 'Team KPI',
    subtitle: 'Quality score rollup by team',
  },
]

export function ReportsPage() {
  usePageTitle('Reports')
  const [activeId, setActiveId] = useState<string>(REPORTS[0].id)
  const active = REPORTS.find((r) => r.id === activeId) ?? REPORTS[0]

  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation />
      <main
        className="mx-auto max-w-[1400px] px-6 pt-24"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="flex gap-6">
          {/* Left sidebar — report list */}
          <aside className="w-56 flex-shrink-0">
            <div className="rounded-lg border border-tertiary bg-primary">
              <div className="border-b border-tertiary px-4 py-3">
                <div className="text-overline uppercase tracking-wide text-tertiary">
                  Reports
                </div>
              </div>
              <div className="p-1">
                {REPORTS.map((r) => {
                  const isActive = r.id === activeId
                  return (
                    <button
                      className={`flex w-full items-start gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors ${
                        isActive
                          ? 'bg-amber-bg text-amber-text'
                          : 'text-secondary hover:bg-secondary hover:text-primary'
                      }`}
                      key={r.id}
                      onClick={() => setActiveId(r.id)}
                    >
                      {r.id === 'team-kpi' ? (
                        <BarChart3 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                      ) : (
                        <TrendingUp className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
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
              <h1 className="text-[18px] font-medium text-primary">
                {active.label}
              </h1>
              <span className="text-sm text-tertiary">{active.subtitle}</span>
            </div>
            {activeId === 'team-kpi' && <TeamKPIReport />}
            {activeId === 'monthly-improvement' && <MonthlyImprovementReport />}
          </div>
        </div>
      </main>
      <CommandBar />
    </div>
  )
}
