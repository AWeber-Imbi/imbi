import {
  ArrowLeft,
  ExternalLink,
  CheckCircle,
  XCircle,
  AlertCircle,
  GitBranch,
  TrendingUp,
  TrendingDown,
  Settings as SettingsIcon,
  Play,
  ArrowRight,
  icons,
} from 'lucide-react'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { Badge } from './ui/badge'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listLinkDefinitions } from '@/api/endpoints'
import type { Project } from '@/types'

interface ProjectDetailProps {
  project: Project
  onBack: () => void
  isDarkMode: boolean
}

type TabType =
  | 'overview'
  | 'configuration'
  | 'components'
  | 'dependencies'
  | 'logs'
  | 'notes'
  | 'operations-log'
  | 'settings'

function getLucideIcon(iconName: string | null | undefined) {
  if (!iconName) return ExternalLink
  const pascalName = iconName
    .split('-')
    .map(s => s.charAt(0).toUpperCase() + s.slice(1))
    .join('') as keyof typeof icons
  return icons[pascalName] || ExternalLink
}

export function ProjectDetail({ project, onBack, isDarkMode }: ProjectDetailProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const [activeTab, setActiveTab] = useState<TabType>('overview')

  // Mock data for aspects not yet available from the API
  const healthScore = 66
  const healthTrend = 'down'

  const deploymentStatus = {
    testing: { version: '1962b02', status: 'success', updated: '2m ago' },
    staging: { version: '1.0.11', status: 'success', updated: '1h ago' },
    prod: { version: '1.0.10', status: 'success', updated: '3h ago' },
  }

  const facts = [
    { label: 'CI Deploy Status', value: 'Pass', status: 'success', icon: CheckCircle },
    { label: 'Configuration System', value: 'SSM Parameter Store', status: 'neutral' },
    { label: 'Data Center', value: 'us-east-1', status: 'neutral' },
    { label: 'Deployment Type', value: 'GitHub Actions', status: 'neutral' },
    { label: 'GitHub Actions Pipeline', value: '\u2713', status: 'success', icon: CheckCircle },
    { label: 'In SonarQube', value: '\u2717', status: 'error', icon: XCircle },
    { label: 'Last Commit Timestamp', value: '2025-11-22 17:23', status: 'neutral' },
    { label: 'Lines of Code', value: 'Not Set', status: 'warning', icon: AlertCircle },
    { label: 'Meets Standards', value: 'Not Set', status: 'warning', icon: AlertCircle },
    { label: 'Orchestration System', value: 'Kubernetes', status: 'neutral' },
    { label: 'Programming Language', value: 'Python 3.12', status: 'neutral' },
    { label: 'SonarQube Analysis Result', value: 'Not Set', status: 'warning', icon: AlertCircle },
  ]

  const feed = [
    { user: 'Scott Miller', action: 'deployed', environment: 'Testing', version: '(1962b02)', time: 'Nov 22, 2025, 12:28 PM' },
    { user: 'Scott Miller', action: 'deployed', environment: 'Production', version: '(1.0.11)', time: 'Nov 21, 2025, 4:09 PM' },
    { user: 'Scott Miller', action: 'deployed', environment: 'Staging', version: '(1.0.11)', time: 'Nov 21, 2025, 4:08 PM' },
    { user: 'Scott Miller', action: 'deployed', environment: 'Testing', version: '(d504611)', time: 'Nov 21, 2025, 4:08 PM' },
    { user: 'Scott Miller', action: 'deployed', environment: 'Production', version: '(1.0.10)', time: 'Nov 21, 2025, 3:50 PM' },
    { user: 'Scott Miller', action: 'deployed', environment: 'Testing', version: '(089f7fd)', time: 'Nov 21, 2025, 3:45 PM' },
  ]

  const getEnvironmentBadgeColor = (env: string) => {
    const envLower = env.toLowerCase()
    if (envLower.includes('prod')) return 'bg-red-100 text-red-700'
    if (envLower.includes('stag')) return 'bg-amber-100 text-amber-700'
    return 'bg-blue-100 text-blue-700'
  }

  const { data: linkDefs = [] } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: () => listLinkDefinitions(orgSlug),
    enabled: !!orgSlug,
  })

  const linkDefMap = Object.fromEntries(
    linkDefs.map(ld => [ld.slug, ld]),
  )

  const externalLinks = Object.entries(project.links || {}).map(([key, url]) => {
    const def = linkDefMap[key]
    return {
      key,
      url: String(url),
      Icon: getLucideIcon(def?.icon),
      label: def?.name || key.replace(/_/g, ' '),
    }
  })

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'components', label: 'Components' },
    { id: 'configuration', label: 'Configuration' },
    { id: 'dependencies', label: 'Dependencies' },
    { id: 'logs', label: 'Logs' },
    { id: 'notes', label: 'Notes' },
    { id: 'operations-log', label: 'Operations Log' },
    { id: 'settings', label: '' },
  ]

  return (
    <div className="max-w-[1600px] mx-auto px-6 py-8">
      {/* Back Button */}
      <Button variant="ghost" size="sm" onClick={onBack} className="mb-4">
        <ArrowLeft className="w-4 h-4 mr-2" />
        Back to Projects
      </Button>

      {/* Project Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-start gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>
                {project.name}
              </h1>
              <Badge variant="outline">{project.project_type.name}</Badge>
            </div>
            <p className={`mb-2 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
              {project.team.name}
            </p>
            {project.description && (
              <p className={`mb-3 max-w-2xl ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                {project.description}
              </p>
            )}

            {/* External Links */}
            {externalLinks.length > 0 && (
              <div className="flex items-center flex-wrap gap-3">
                {externalLinks.map(({ key, url, Icon, label }, index) => (
                  <span key={key} className="flex items-center gap-1.5">
                    {index > 0 && <span className={isDarkMode ? 'text-gray-600 mr-1.5' : 'text-slate-300 mr-1.5'}>|</span>}
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-blue-600 text-sm hover:underline"
                    >
                      <Icon className="w-4 h-4" />
                      <span>{label}</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-start gap-6">
          {/* Deployment Pipeline (mocked) */}
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs bg-blue-100 text-blue-700 px-2.5 py-1 rounded">
                Testing: {deploymentStatus.testing.version}
              </span>
              <ArrowRight className="w-4 h-4 text-slate-400" />
              <span className="text-xs bg-amber-100 text-amber-700 px-2.5 py-1 rounded">
                Staging: {deploymentStatus.staging.version}
              </span>
              <ArrowRight className="w-4 h-4 text-slate-400" />
              <span className="text-xs bg-red-100 text-red-700 px-2.5 py-1 rounded">
                Prod: {deploymentStatus.prod.version}
              </span>
            </div>
            <Button size="sm" className="self-end bg-blue-700 hover:bg-blue-800">
              <Play className="w-4 h-4 mr-1" />
              Deploy
            </Button>
          </div>

          {/* Health Score (mocked) */}
          <div className="flex items-center gap-2">
            <div className="text-right">
              <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
                Health Score
              </p>
              <div className="flex items-center gap-2 justify-end">
                {healthTrend === 'down' ? (
                  <TrendingDown className="w-4 h-4 text-red-600" />
                ) : (
                  <TrendingUp className="w-4 h-4 text-green-600" />
                )}
                <span className={`text-2xl ${healthScore >= 70 ? 'text-amber-600' : 'text-red-600'}`}>
                  {healthScore}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className={`border-b mb-6 ${isDarkMode ? 'border-gray-700' : 'border-slate-200'}`}>
        <div className="flex gap-6 overflow-x-auto">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-3 border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'border-blue-600 text-blue-600'
                  : `border-transparent ${isDarkMode ? 'text-gray-400 hover:text-gray-200' : 'text-slate-600 hover:text-slate-900'} hover:border-slate-300`
              }`}
            >
              {tab.id === 'settings' ? (
                <SettingsIcon className="w-4 h-4" />
              ) : (
                tab.label
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Project Information */}
          <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className={isDarkMode ? 'text-white' : 'text-slate-900'}>Project Information</h3>
              <Button variant="ghost" size="sm">Edit</Button>
            </div>

            <div className="space-y-4">
              <div>
                <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>Team</p>
                <p className={isDarkMode ? 'text-white' : 'text-slate-900'}>{project.team.name}</p>
              </div>

              <div>
                <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>Project Type</p>
                <p className={isDarkMode ? 'text-white' : 'text-slate-900'}>{project.project_type.name}</p>
              </div>

              <div>
                <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>Slug</p>
                <p className={`font-mono text-sm px-2 py-1 rounded ${isDarkMode ? 'text-white bg-gray-700' : 'text-slate-900 bg-slate-100'}`}>
                  {project.slug}
                </p>
              </div>

              <div>
                <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>Environments</p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {(project.environments || []).map((env, index) => (
                    <span
                      key={index}
                      className={`px-2 py-1 rounded text-xs ${getEnvironmentBadgeColor(env.name)}`}
                    >
                      {env.name}
                    </span>
                  ))}
                  {(!project.environments || project.environments.length === 0) && (
                    <span className={`text-sm ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>
                      No environments
                    </span>
                  )}
                </div>
              </div>

              {project.identifiers && Object.keys(project.identifiers).length > 0 && (
                <div className="pt-4">
                  <p className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>
                    Project Identifiers
                  </p>
                  <div className="space-y-2">
                    {Object.entries(project.identifiers).map(([owner, id]) => (
                      <div key={owner} className="flex items-center justify-between text-sm">
                        <span className={isDarkMode ? 'text-gray-300' : 'text-slate-600'}>{owner}</span>
                        <span className={`font-mono px-2 py-0.5 rounded ${isDarkMode ? 'text-white bg-gray-700' : 'text-slate-900 bg-slate-100'}`}>
                          {id}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Project Facts (mocked) */}
          <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className={isDarkMode ? 'text-white' : 'text-slate-900'}>Project Facts</h3>
              <Button variant="ghost" size="sm">Update Facts</Button>
            </div>

            <div className="space-y-3">
              {facts.map((fact, index) => {
                const Icon = fact.icon
                return (
                  <div key={index} className="flex items-center justify-between py-2 border-l-2 border-blue-500 pl-3">
                    <span className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}>
                      {fact.label}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm ${
                        fact.status === 'success' ? 'text-green-700' :
                        fact.status === 'error' ? 'text-red-700' :
                        fact.status === 'warning' ? 'text-amber-700' :
                        isDarkMode ? 'text-white' : 'text-slate-900'
                      }`}>
                        {fact.value}
                      </span>
                      {Icon && (
                        <Icon className={`w-3.5 h-3.5 ${
                          fact.status === 'success' ? 'text-green-600' :
                          fact.status === 'error' ? 'text-red-600' :
                          fact.status === 'warning' ? 'text-amber-600' :
                          'text-slate-400'
                        }`} />
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            <p className={`text-xs mt-4 text-center ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>
              Last Updated: 11/22/2025
            </p>
          </Card>

          {/* Recent Activity (mocked) */}
          <Card className={`p-6 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
            <h3 className={`mb-4 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>Recent Activity</h3>

            <div className="space-y-4">
              {feed.map((item, index) => (
                <div key={index} className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                    isDarkMode ? 'bg-gray-700' : 'bg-slate-100'
                  }`}>
                    <GitBranch className={`w-4 h-4 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm leading-relaxed ${isDarkMode ? 'text-gray-200' : 'text-slate-900'}`}>
                      <span className="font-medium">{item.user}</span>{' '}
                      <span className={isDarkMode ? 'text-gray-400' : 'text-slate-600'}>{item.action}</span>{' '}
                      <span className="font-medium">{project.name}</span>{' '}
                      <span className={isDarkMode ? 'text-gray-400' : 'text-slate-600'}>to</span>{' '}
                      <span className={`font-medium ${
                        item.environment === 'Production' ? 'text-red-700' :
                        item.environment === 'Staging' ? 'text-amber-700' :
                        'text-blue-700'
                      }`}>
                        {item.environment}
                      </span>
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>{item.time}</span>
                      <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-slate-400'}`}>&bull;</span>
                      <span className={`text-xs font-mono ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}>{item.version}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'configuration' && (
        <PlaceholderTab name="Configuration" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'dependencies' && (
        <PlaceholderTab name="Dependencies" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'components' && (
        <PlaceholderTab name="Components" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'logs' && (
        <PlaceholderTab name="Logs" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'notes' && (
        <PlaceholderTab name="Notes" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'operations-log' && (
        <PlaceholderTab name="Operations Log" isDarkMode={isDarkMode} />
      )}
      {activeTab === 'settings' && (
        <PlaceholderTab name="Settings" isDarkMode={isDarkMode} />
      )}
    </div>
  )
}

function PlaceholderTab({ name, isDarkMode }: { name: string; isDarkMode: boolean }) {
  return (
    <Card className={`p-12 ${isDarkMode ? 'bg-gray-800 border-gray-700' : ''}`}>
      <div className="text-center">
        <h3 className={`text-lg mb-2 ${isDarkMode ? 'text-white' : 'text-slate-900'}`}>{name}</h3>
        <p className={isDarkMode ? 'text-gray-400' : 'text-slate-500'}>
          This tab will be implemented in a future update.
        </p>
      </div>
    </Card>
  )
}
