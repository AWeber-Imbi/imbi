import {
  AlertTriangle,
  CheckCircle,
  ChevronRight,
  TrendingDown,
  TrendingUp,
  XCircle,
} from 'lucide-react'

import { Card } from '@/components/ui/card'

interface TeamActivityWidgetProps {
  onViewChange?: (view: ViewChangeEvent) => void
}

interface ViewChangeEvent {
  filter: Record<string, string>
  view: string
}

export function TeamActivityWidget({ onViewChange }: TeamActivityWidgetProps) {
  const teams = [
    {
      deployments: 12,
      health: 92,
      healthTrend: 'up' as const,
      name: 'Platform Support Engineering',
      projects: 45,
    },
    {
      deployments: 8,
      health: 88,
      healthTrend: 'up' as const,
      name: 'Database Administration',
      projects: 23,
    },
    {
      deployments: 34,
      health: 85,
      healthTrend: 'down' as const,
      name: 'Content Creation',
      projects: 84,
    },
    {
      deployments: 22,
      health: 89,
      healthTrend: 'up' as const,
      name: 'Control Panel',
      projects: 70,
    },
    {
      deployments: 18,
      health: 91,
      healthTrend: 'up' as const,
      name: 'Email Delivery',
      projects: 56,
    },
    {
      deployments: 15,
      health: 87,
      healthTrend: 'down' as const,
      name: 'Frontend BoF',
      projects: 38,
    },
  ]

  const getHealthColor = (health: number) => {
    if (health >= 90) return 'text-success'
    if (health >= 75) return 'text-warning'
    return 'text-danger'
  }

  const getHealthIcon = (health: number) => {
    if (health >= 90) return CheckCircle
    if (health >= 75) return AlertTriangle
    return XCircle
  }

  const handleTeamClick = (teamName: string) => {
    onViewChange?.({ filter: { team: teamName }, view: 'projects' })
  }

  const handleDeploymentClick = (e: React.MouseEvent, teamName: string) => {
    e.stopPropagation()
    onViewChange?.({ filter: { team: teamName }, view: 'deployments' })
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-primary text-lg">Team Activity</h3>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {teams.map((team) => {
          const HealthIcon = getHealthIcon(team.health)
          const healthColor = getHealthColor(team.health)

          return (
            <div
              className="border-input bg-background hover:border-secondary focus-visible:ring-ring cursor-pointer rounded-lg border p-4 text-left transition-all hover:shadow-sm focus:outline-none focus-visible:ring-2"
              key={team.name}
              onClick={() => handleTeamClick(team.name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleTeamClick(team.name)
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex-1">
                  <div className="text-primary mb-1 font-medium">
                    {team.name}
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <HealthIcon className={`size-4 ${healthColor}`} />
                    <span className={healthColor}>{team.health}%</span>
                    {team.healthTrend === 'up' ? (
                      <TrendingUp className="size-3 text-green-500" />
                    ) : (
                      <TrendingDown className="size-3 text-red-500" />
                    )}
                  </div>
                </div>
                <ChevronRight className="text-tertiary size-5" />
              </div>

              <div className="flex items-center gap-3">
                <div className="text-secondary text-sm">
                  {team.projects} projects
                </div>
                <div className="text-secondary text-sm">•</div>
                <button
                  className="text-info hover:text-info/80 text-sm"
                  onClick={(e) => handleDeploymentClick(e, team.name)}
                  type="button"
                >
                  {team.deployments} deployments
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
