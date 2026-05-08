import { CheckCircle, Folder, Rocket } from 'lucide-react'

import { Card } from '@/components/ui/card'

import type { StatsResponse } from './api'

interface StatsProps {
  data: StatsResponse | undefined
}

interface TileProps {
  icon: React.ReactNode
  label: string
  sub?: string
  value: string
}

export function StatisticsCard({ data }: StatsProps) {
  const deployments = data?.deployments
  const successPct =
    deployments && deployments.success_rate !== null
      ? Math.round(deployments.success_rate * 100)
      : null
  const successDenominator = deployments?.total ?? 0
  const successNumerator = deployments
    ? deployments.total - deployments.rolled_back
    : 0

  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile
        icon={<Rocket className="h-4 w-4" />}
        label="Total deployments"
        sub={
          deployments?.rolled_back
            ? `${deployments.rolled_back.toLocaleString()} rolled back`
            : undefined
        }
        value={deployments ? deployments.total.toLocaleString() : '—'}
      />
      <Tile
        icon={<Folder className="h-4 w-4" />}
        label="Projects touched"
        value={
          data?.projects_touched !== undefined
            ? data.projects_touched.toLocaleString()
            : '—'
        }
      />
      <Tile
        icon={<CheckCircle className="h-4 w-4" />}
        label="Success rate"
        sub={
          successDenominator > 0
            ? `${successNumerator} of ${successDenominator} deployments succeeded`
            : undefined
        }
        value={successPct !== null ? `${successPct}%` : '—'}
      />
    </section>
  )
}

function Tile({ icon, label, sub, value }: TileProps) {
  return (
    <Card className="rounded-md border border-tertiary p-4 shadow-none">
      <div className="flex items-center gap-2 text-xs text-tertiary">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold text-primary">{value}</div>
      {sub && <div className="mt-1 text-xs text-secondary">{sub}</div>}
    </Card>
  )
}
