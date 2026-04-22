import {
  TrendingUp,
  TrendingDown,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronRight,
} from 'lucide-react'
import { Card } from '@/components/ui/card'

interface ViewChangeEvent {
  view: string
  filter: Record<string, string>
}

interface TeamActivityWidgetProps {
  onViewChange?: (view: ViewChangeEvent) => void
}

export function TeamActivityWidget({ onViewChange }: TeamActivityWidgetProps) {
  const teams = [
    {
      name: 'Platform Support Engineering',
      health: 92,
      healthTrend: 'up' as const,
      projects: 45,
      deployments: 12,
    },
    {
      name: 'Database Administration',
      health: 88,
      healthTrend: 'up' as const,
      projects: 23,
      deployments: 8,
    },
    {
      name: 'Content Creation',
      health: 85,
      healthTrend: 'down' as const,
      projects: 84,
      deployments: 34,
    },
    {
      name: 'Control Panel',
      health: 89,
      healthTrend: 'up' as const,
      projects: 70,
      deployments: 22,
    },
    {
      name: 'Email Delivery',
      health: 91,
      healthTrend: 'up' as const,
      projects: 56,
      deployments: 18,
    },
    {
      name: 'Frontend BoF',
      health: 87,
      healthTrend: 'down' as const,
      projects: 38,
      deployments: 15,
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
    onViewChange?.({ view: 'projects', filter: { team: teamName } })
  }

  const handleDeploymentClick = (e: React.MouseEvent, teamName: string) => {
    e.stopPropagation()
    onViewChange?.({ view: 'deployments', filter: { team: teamName } })
  }

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg text-primary">Team Activity</h3>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {teams.map((team) => {
          const HealthIcon = getHealthIcon(team.health)
          const healthColor = getHealthColor(team.health)

          return (
            <div
              key={team.name}
              role="button"
              tabIndex={0}
              onClick={() => handleTeamClick(team.name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleTeamClick(team.name)
                }
              }}
              className={`cursor-pointer rounded-lg border border-input bg-background p-4 text-left transition-all hover:border-secondary hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex-1">
                  <div className="mb-1 font-medium text-primary">
                    {team.name}
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <HealthIcon className={`h-4 w-4 ${healthColor}`} />
                    <span className={healthColor}>{team.health}%</span>
                    {team.healthTrend === 'up' ? (
                      <TrendingUp className="h-3 w-3 text-green-500" />
                    ) : (
                      <TrendingDown className="h-3 w-3 text-red-500" />
                    )}
                  </div>
                </div>
                <ChevronRight className="h-5 w-5 text-tertiary" />
              </div>

              <div className="flex items-center gap-3">
                <div className="text-sm text-secondary">
                  {team.projects} projects
                </div>
                <div className="text-sm text-secondary">•</div>
                <button
                  type="button"
                  onClick={(e) => handleDeploymentClick(e, team.name)}
                  className="hover:text-info/80 text-sm text-info"
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
