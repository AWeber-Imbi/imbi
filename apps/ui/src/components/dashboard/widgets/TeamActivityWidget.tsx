import { TrendingUp, TrendingDown, CheckCircle, XCircle, AlertTriangle, ChevronRight } from 'lucide-react'
import { Card } from '../../ui/card'

interface TeamActivityWidgetProps {
  isDarkMode: boolean
  onViewChange?: (view: any) => void
}

export function TeamActivityWidget({ isDarkMode, onViewChange }: TeamActivityWidgetProps) {
  const teams = [
    { name: 'Platform Support Engineering', health: 92, healthTrend: 'up' as const, projects: 45, deployments: 12 },
    { name: 'Database Administration', health: 88, healthTrend: 'up' as const, projects: 23, deployments: 8 },
    { name: 'Content Creation', health: 85, healthTrend: 'down' as const, projects: 84, deployments: 34 },
    { name: 'Control Panel', health: 89, healthTrend: 'up' as const, projects: 70, deployments: 22 },
    { name: 'Email Delivery', health: 91, healthTrend: 'up' as const, projects: 56, deployments: 18 },
    { name: 'Frontend BoF', health: 87, healthTrend: 'down' as const, projects: 38, deployments: 15 }
  ]

  const getHealthColor = (health: number) => {
    if (health >= 90) return isDarkMode ? 'text-green-400' : 'text-green-600'
    if (health >= 75) return isDarkMode ? 'text-yellow-400' : 'text-yellow-600'
    return isDarkMode ? 'text-red-400' : 'text-red-600'
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
    <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-lg ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Team Activity
        </h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {teams.map((team) => {
          const HealthIcon = getHealthIcon(team.health)
          const healthColor = getHealthColor(team.health)

          return (
            <button
              key={team.name}
              onClick={() => handleTeamClick(team.name)}
              className={`p-4 rounded-lg border text-left transition-all ${
                isDarkMode
                  ? 'bg-gray-750 border-gray-600 hover:border-gray-500 hover:bg-gray-700'
                  : 'bg-white border-gray-200 hover:border-gray-300 hover:shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <div className={`font-medium mb-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                    {team.name}
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <HealthIcon className={`w-4 h-4 ${healthColor}`} />
                    <span className={healthColor}>{team.health}%</span>
                    {team.healthTrend === 'up' ? (
                      <TrendingUp className="w-3 h-3 text-green-500" />
                    ) : (
                      <TrendingDown className="w-3 h-3 text-red-500" />
                    )}
                  </div>
                </div>
                <ChevronRight className={`w-5 h-5 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`} />
              </div>

              <div className="flex items-center gap-3">
                <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                  {team.projects} projects
                </div>
                <div className={`text-sm ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`}>•</div>
                <button
                  onClick={(e) => handleDeploymentClick(e, team.name)}
                  className={`text-sm ${isDarkMode ? 'text-blue-400 hover:text-blue-300' : 'text-[#2A4DD0] hover:text-blue-700'}`}
                >
                  {team.deployments} deployments
                </button>
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}
