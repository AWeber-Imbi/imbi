import {
  ExternalLink,
  TrendingUp,
  TrendingDown,
  Settings as SettingsIcon,
  ArrowRight,
  Plus,
  Rocket,
} from 'lucide-react'
import { getIcon } from '@/lib/icons'
import { resolveColor, resolveIcon } from '@/lib/ui-maps'
import type { XUiMaps } from '@/lib/ui-maps'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'
import { useMemo, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { useQuery } from '@tanstack/react-query'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  listLinkDefinitions,
  getProjectSchema,
  getProjectRelationships,
} from '@/api/endpoints'
import type { ProjectSchemaSection } from '@/api/endpoints'
import { getTypeColor } from '@/lib/project-colors'
import type { Project, ProjectRelationship } from '@/types'
import { Link } from 'react-router-dom'

interface ProjectDetailProps {
  project: Project
  isDarkMode: boolean
}

type TabType =
  | 'overview'
  | 'configuration'
  | 'components'
  | 'relationships'
  | 'logs'
  | 'notes'
  | 'operations-log'
  | 'settings'

const COLOR_TEXT: Record<string, string> = {
  green: 'text-green-600',
  red: 'text-red-600',
  amber: 'text-amber-600',
  yellow: 'text-yellow-600',
  blue: 'text-blue-600',
  gray: 'text-gray-500',
  grey: 'text-gray-500',
}

/** Format a snake_case or camelCase key as a readable label */
const WORD_OVERRIDES: Record<string, string> = {
  aws: 'AWS',
  ci: 'CI',
  github: 'GitHub',
  gitlab: 'GitLab',
  sonarqube: 'SonarQube',
}

function formatFieldKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .split(' ')
    .map((w) => WORD_OVERRIDES[w.toLowerCase()] ?? w)
    .join(' ')
}

/** Render a field value as a display string using schema metadata for formatting. */
function formatFieldValue(
  value: unknown,
  def?: {
    type?: string | null
    format?: string | null
    minimum?: number | null
    maximum?: number | null
  },
): string | null {
  if (value === null || value === undefined || value === '') return null

  const raw = String(value).trim()
  if (raw === '') return null

  const type = def?.type
  const format = def?.format

  // Booleans — stored as strings "true"/"false" from Neo4j
  if (type === 'boolean' || raw === 'true' || raw === 'false') {
    return raw === 'true' ? 'True' : 'False'
  }

  // Dates and datetimes — display as relative time
  if (format === 'date-time' || format === 'date') {
    const d = new Date(raw)
    if (!isNaN(d.getTime())) {
      return formatDistanceToNow(d, { addSuffix: true })
    }
  }

  // Integers
  if (type === 'integer') {
    const n = parseInt(raw, 10)
    if (!isNaN(n)) return n.toLocaleString()
  }

  // Numbers / floats
  if (type === 'number') {
    const n = parseFloat(raw)
    if (!isNaN(n)) {
      if (def?.minimum === 0 && def?.maximum === 100) {
        return (
          n.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }) + '%'
        )
      }
      return n.toLocaleString()
    }
  }

  if (typeof value === 'object') return JSON.stringify(value)
  return raw
}

function resolveFieldValue(
  key: string,
  _section: ProjectSchemaSection,
  project: Project,
): unknown {
  // Determine if this section is environment-scoped by checking if any
  // of the project's environments has a matching value for this key.
  // The API already filtered sections to only applicable envs, so if the
  // project-level value is absent, check environment objects.
  const projectValue = project[key]
  if (
    projectValue !== null &&
    projectValue !== undefined &&
    projectValue !== ''
  ) {
    return projectValue
  }
  // Fall back to environment objects (e.g. url, or any env-scoped field)
  for (const env of project.environments || []) {
    const envVal = env[key]
    if (envVal !== null && envVal !== undefined && envVal !== '') {
      return envVal
    }
  }
  return undefined
}

export function ProjectDetail({ project, isDarkMode }: ProjectDetailProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  // Mock data for aspects not yet available from the API
  const healthScore = 66
  const healthTrend = 'down'

  const deploymentStatus: Record<
    string,
    { version: string; status: string; updated: string }
  > = {
    'infrastructure-testing': {
      version: '1962b02',
      status: 'success',
      updated: '2m ago',
    },
    testing: { version: '1962b02', status: 'success', updated: '2m ago' },
    staging: { version: '1.0.11', status: 'success', updated: '1h ago' },
    production: { version: '1.0.10', status: 'success', updated: '3h ago' },
  }

  const feed = [
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Testing',
      version: '(1962b02)',
      time: 'Nov 22, 2025, 12:28 PM',
    },
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Production',
      version: '(1.0.11)',
      time: 'Nov 21, 2025, 4:09 PM',
    },
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Staging',
      version: '(1.0.11)',
      time: 'Nov 21, 2025, 4:08 PM',
    },
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Testing',
      version: '(d504611)',
      time: 'Nov 21, 2025, 4:08 PM',
    },
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Production',
      version: '(1.0.10)',
      time: 'Nov 21, 2025, 3:50 PM',
    },
    {
      user: 'Scott Miller',
      action: 'deployed in',
      environment: 'Testing',
      version: '(089f7fd)',
      time: 'Nov 21, 2025, 3:45 PM',
    },
  ]

  const sortedEnvironments = useMemo(
    () =>
      [...(project.environments || [])].sort((a, b) => {
        const orderDiff = (a.sort_order ?? 0) - (b.sort_order ?? 0)
        return orderDiff !== 0 ? orderDiff : a.name.localeCompare(b.name)
      }),
    [project.environments],
  )

  const { data: linkDefs = [] } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: () => listLinkDefinitions(orgSlug),
    enabled: !!orgSlug,
  })

  const { data: projectSchema } = useQuery({
    queryKey: ['projectSchema', orgSlug, project.id],
    queryFn: () => getProjectSchema(orgSlug, project.id),
    enabled: !!orgSlug,
  })

  const linkDefMap = Object.fromEntries(linkDefs.map((ld) => [ld.slug, ld]))

  const externalLinks = Object.entries(project.links || {})
    .map(([key, url]) => {
      const raw = String(url)
      let safeUrl: string | null = null
      try {
        const parsed = new URL(raw)
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
          safeUrl = parsed.toString()
        }
      } catch {
        safeUrl = null
      }
      if (!safeUrl) return null
      const def = linkDefMap[key]
      return {
        key,
        url: safeUrl,
        Icon: getIcon(def?.icon),
        label: def?.name || key.replace(/_/g, ' '),
      }
    })
    .filter((link): link is NonNullable<typeof link> => link !== null)

  const attributeFields = useMemo(() => {
    if (!projectSchema) return []
    const seen = new Set<string>()
    const fields: {
      key: string
      label: string
      value: string | null
      rawValue: unknown
      title?: string
      uiMaps: XUiMaps
    }[] = []
    for (const section of projectSchema.sections) {
      for (const [key, def] of Object.entries(section.properties)) {
        if (seen.has(key) || key === 'url') continue
        seen.add(key)
        const raw = resolveFieldValue(key, section, project)
        const isDate = def.format === 'date-time' || def.format === 'date'
        const xUi = def['x-ui']
        fields.push({
          key,
          label: def.title || formatFieldKey(key),
          value: formatFieldValue(raw, def),
          rawValue: raw,
          title:
            isDate && raw != null
              ? new Date(String(raw)).toLocaleString()
              : undefined,
          uiMaps: {
            colorMap: xUi?.['color-map'] ?? undefined,
            iconMap: xUi?.['icon-map'] ?? undefined,
            colorRange: xUi?.['color-range'] ?? undefined,
            iconRange: xUi?.['icon-range'] ?? undefined,
            colorAge: xUi?.['color-age'] ?? undefined,
            iconAge: xUi?.['icon-age'] ?? undefined,
          },
        })
      }
    }
    return fields.sort((a, b) => a.label.localeCompare(b.label))
  }, [projectSchema, project])

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'components', label: 'Components' },
    { id: 'configuration', label: 'Configuration' },
    {
      id: 'relationships',
      label: (() => {
        const rel = project.relationships
        const total = (rel?.inbound_count ?? 0) + (rel?.outbound_count ?? 0)
        return `Relationships (${total})`
      })(),
    },
    { id: 'logs', label: 'Logs' },
    { id: 'notes', label: 'Notes' },
    { id: 'operations-log', label: 'Operations Log' },
    { id: 'settings', label: '' },
  ]

  const label = isDarkMode ? 'text-gray-400' : 'text-slate-500'
  const value = isDarkMode ? 'text-white' : 'text-slate-900'
  const muted = isDarkMode ? 'text-gray-600' : 'text-slate-400'
  const divider = isDarkMode ? 'border-gray-700' : 'border-slate-100'

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      {/* Project Header */}
      <div className="mb-6 pl-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="mb-1 flex items-center gap-3">
              <h1 className={`text-[1.75rem] ${value}`}>{project.name}</h1>
              <Badge variant="outline">
                {(project.project_types || []).map((pt) => pt.name).join(', ')}
              </Badge>
            </div>
          </div>

          {/* Deployment Pipeline (mocked) */}
          <div className="flex items-center gap-2">
            {sortedEnvironments
              .filter((env) => !!deploymentStatus[env.slug])
              .map((env, idx) => {
                const deployment = deploymentStatus[env.slug]
                const color = env.label_color
                return (
                  <span key={env.slug} className="contents">
                    {idx > 0 && (
                      <ArrowRight className="h-4 w-4 text-slate-400" />
                    )}
                    <span
                      className="inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium"
                      style={
                        color
                          ? {
                              backgroundColor: color + '20',
                              color: color,
                              border: `1px solid ${color}40`,
                            }
                          : undefined
                      }
                    >
                      {env.name}: {deployment.version}
                    </span>
                  </span>
                )
              })}
            <Button
              variant="outline"
              size="sm"
              className="ml-4 border-amber-400 bg-amber-50 text-amber-800 hover:bg-amber-100"
            >
              <Rocket className="mr-1 h-4 w-4" />
              Deploy
            </Button>
          </div>
        </div>

        {project.description && (
          <p
            className={`mt-3 ${isDarkMode ? 'text-gray-300' : 'text-slate-600'}`}
          >
            {project.description}
          </p>
        )}

        {/* External Links */}
        {externalLinks.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {externalLinks.map(
              ({ key, url, Icon, label: linkLabel }, index) => (
                <span key={key} className="flex items-center gap-1.5">
                  {index > 0 && (
                    <span
                      className={`mr-1.5 ${isDarkMode ? 'text-gray-600' : 'text-slate-300'}`}
                    >
                      |
                    </span>
                  )}
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`flex items-center gap-1.5 text-sm ${isDarkMode ? 'text-amber-400' : 'text-amber-text'} hover:underline`}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{linkLabel}</span>
                  </a>
                </span>
              ),
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList className="mb-6">
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.id}
              value={tab.id}
              aria-label={tab.id === 'settings' ? 'Settings' : undefined}
            >
              {tab.id === 'settings' ? (
                <SettingsIcon className="h-4 w-4" />
              ) : (
                tab.label
              )}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[3fr_2fr]">
            {/* Left column: Details */}
            <div className="space-y-6">
              <Card
                className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
              >
                <div className="mb-4 flex items-center justify-between">
                  <h3 className={value}>Project Details</h3>
                  <Button variant="ghost" size="sm">
                    Edit
                  </Button>
                </div>

                <div className="space-y-0">
                  <div
                    className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                  >
                    <span className={`text-sm ${label}`}>Team</span>
                    <span className={`text-sm ${value}`}>
                      {project.team.name}
                    </span>
                  </div>

                  <div
                    className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                  >
                    <span className={`text-sm ${label}`}>Slug</span>
                    <span
                      className={`rounded px-2 py-0.5 font-mono text-sm ${isDarkMode ? 'bg-gray-700 text-white' : 'bg-slate-100 text-slate-900'}`}
                    >
                      {project.slug}
                    </span>
                  </div>

                  {project.created_at && (
                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Created</span>
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className={`text-sm ${value} cursor-help underline decoration-dotted`}
                            >
                              {formatDistanceToNow(
                                new Date(project.created_at),
                                { addSuffix: true },
                              )}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>
                              {new Date(project.created_at).toLocaleString()}
                            </p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  )}

                  {/* Blueprint attributes */}
                  {attributeFields.map(
                    ({
                      key,
                      label: fieldLabel,
                      value: fieldValue,
                      rawValue,
                      title: fieldTitle,
                      uiMaps,
                    }) => {
                      const mappedColor = resolveColor(uiMaps, rawValue)
                      const mappedIcon = resolveIcon(uiMaps, rawValue)
                      const FieldIcon = mappedIcon ? getIcon(mappedIcon) : null
                      const textColorClass = mappedColor
                        ? (COLOR_TEXT[mappedColor] ?? value)
                        : value
                      return (
                        <div
                          key={key}
                          className={`flex items-center justify-between border-b py-1.5 ${divider} last:border-0`}
                        >
                          <span className={`text-sm ${label}`}>
                            {fieldLabel}
                          </span>
                          {fieldValue !== null ? (
                            <span className="flex items-center gap-1.5">
                              {FieldIcon && (
                                <FieldIcon
                                  className={`h-3.5 w-3.5 flex-shrink-0 ${textColorClass}`}
                                />
                              )}
                              {fieldTitle ? (
                                <TooltipProvider delayDuration={200}>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <span
                                        className={`text-sm ${textColorClass} cursor-help underline decoration-dotted`}
                                      >
                                        {fieldValue}
                                      </span>
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      <p>{fieldTitle}</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </TooltipProvider>
                              ) : (
                                <span className={`text-sm ${textColorClass}`}>
                                  {fieldValue}
                                </span>
                              )}
                            </span>
                          ) : (
                            <span className={`text-sm italic ${muted}`}>
                              Not set
                            </span>
                          )}
                        </div>
                      )
                    },
                  )}
                </div>
              </Card>

              {/* Identifiers */}
              {project.identifiers &&
                Object.keys(project.identifiers).length > 0 && (
                  <Card
                    className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
                  >
                    <h3 className={`mb-4 ${value}`}>Identifiers</h3>
                    <div className="space-y-0">
                      {Object.entries(project.identifiers)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([owner, id]) => (
                          <div
                            key={owner}
                            className={`flex items-center justify-between border-b py-2 ${divider} last:border-0`}
                          >
                            <span className={`text-sm ${label}`}>{owner}</span>
                            <span
                              className={`rounded px-2 py-0.5 font-mono text-sm ${isDarkMode ? 'bg-gray-700 text-white' : 'bg-slate-100 text-slate-900'}`}
                            >
                              {id}
                            </span>
                          </div>
                        ))}
                    </div>
                  </Card>
                )}
            </div>

            {/* Right column: Health & Compliance + Recent Activity */}
            <div className="space-y-6">
              {/* Health & Compliance */}
              <Card
                className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
              >
                <h3 className={`mb-4 ${value}`}>Health &amp; Compliance</h3>

                <div className="mb-4 flex items-center gap-3">
                  <div
                    className={`flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-lg text-2xl font-medium ${
                      healthScore >= 90
                        ? 'bg-green-50 text-green-700'
                        : healthScore >= 80
                          ? 'bg-emerald-50 text-emerald-700'
                          : healthScore >= 70
                            ? 'bg-amber-50 text-amber-700'
                            : 'bg-red-50 text-red-700'
                    }`}
                  >
                    {healthScore}
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      {healthTrend === 'down' ? (
                        <TrendingDown className="h-4 w-4 text-red-600" />
                      ) : (
                        <TrendingUp className="h-4 w-4 text-green-600" />
                      )}
                      <span
                        className={`text-sm ${healthTrend === 'down' ? 'text-red-600' : 'text-green-600'}`}
                      >
                        {healthTrend === 'down' ? 'Declining' : 'Improving'}
                      </span>
                    </div>
                    <p className={`text-xs ${muted}`}>Health score</p>
                  </div>
                </div>

                <p className={`text-sm ${muted}`}>
                  Policy scoring and compliance checks will appear here.
                </p>
              </Card>

              {/* Environments */}
              {sortedEnvironments.length > 0 && (
                <Card
                  className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
                >
                  <h3 className={`mb-4 ${value}`}>Environments</h3>
                  <div className="space-y-0">
                    {sortedEnvironments.map((env) => {
                      let url: string | null = null
                      if (typeof env.url === 'string' && env.url !== '') {
                        try {
                          const parsed = new URL(env.url)
                          if (
                            parsed.protocol === 'http:' ||
                            parsed.protocol === 'https:'
                          ) {
                            url = parsed.toString()
                          }
                        } catch {
                          url = null
                        }
                      }
                      return (
                        <div
                          key={env.slug}
                          className={`flex items-center justify-between border-b py-2 ${divider} last:border-0`}
                        >
                          <EnvironmentBadge
                            name={env.name}
                            slug={env.slug}
                            label_color={env.label_color}
                          />
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={`flex items-center gap-1.5 text-sm ${isDarkMode ? 'text-amber-400' : 'text-amber-text'} hover:underline`}
                            >
                              {url}
                              <ExternalLink
                                className={`h-3 w-3 ${isDarkMode ? 'text-amber-400' : 'text-amber-text'}`}
                              />
                            </a>
                          ) : (
                            <span className={`text-sm ${muted}`}>—</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </Card>
              )}

              {/* Recent Activity (mocked) */}
              <Card
                className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
              >
                <h3 className={`mb-4 ${value}`}>Recent Activity</h3>

                <div className="space-y-4">
                  {feed.map((item, index) => (
                    <div key={index} className="flex items-start gap-2.5">
                      <div className="min-w-0 flex-1">
                        <p className={`text-sm leading-snug ${value}`}>
                          <span className="font-medium">{item.user}</span>{' '}
                          <span className={label}>{item.action}</span>{' '}
                          <span
                            style={{
                              color:
                                project.environments?.find(
                                  (e) => e.name === item.environment,
                                )?.label_color || undefined,
                            }}
                          >
                            {item.environment}
                          </span>
                        </p>
                        <div className="mt-0.5 flex items-center gap-1.5">
                          <span className={`text-xs ${muted}`}>
                            {item.time}
                          </span>
                          <span className={`text-xs ${muted}`}>&bull;</span>
                          <span
                            className={`font-mono text-xs ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`}
                          >
                            {item.version}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="configuration">
          <PlaceholderTab name="Configuration" isDarkMode={isDarkMode} />
        </TabsContent>
        <TabsContent value="relationships">
          <RelationshipsTab
            orgSlug={project.team.organization.slug}
            projectId={project.id}
            projectName={project.name}
            isDarkMode={isDarkMode}
          />
        </TabsContent>
        <TabsContent value="components">
          <PlaceholderTab name="Components" isDarkMode={isDarkMode} />
        </TabsContent>
        <TabsContent value="logs">
          <PlaceholderTab name="Logs" isDarkMode={isDarkMode} />
        </TabsContent>
        <TabsContent value="notes">
          <PlaceholderTab name="Notes" isDarkMode={isDarkMode} />
        </TabsContent>
        <TabsContent value="operations-log">
          <PlaceholderTab name="Operations Log" isDarkMode={isDarkMode} />
        </TabsContent>
        <TabsContent value="settings">
          <PlaceholderTab name="Settings" isDarkMode={isDarkMode} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

type RelationshipFilter = 'all' | 'uses' | 'used-by'

interface RelationshipsTabProps {
  orgSlug: string
  projectId: string
  projectName: string
  isDarkMode: boolean
}

function RelationshipsTab({
  orgSlug,
  projectId,
  projectName,
  isDarkMode,
}: RelationshipsTabProps) {
  const [filter, setFilter] = useState<RelationshipFilter>('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['project-relationships', orgSlug, projectId],
    queryFn: () => getProjectRelationships(orgSlug, projectId),
  })

  const cardClass = `p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`
  const sub = isDarkMode ? 'text-gray-400' : 'text-slate-500'

  if (isLoading) {
    return (
      <Card className={cardClass}>
        <p className={sub}>Loading relationships...</p>
      </Card>
    )
  }
  if (error) {
    return (
      <Card className={cardClass}>
        <p className={sub}>Failed to load relationships.</p>
      </Card>
    )
  }

  const rels: ProjectRelationship[] = data?.relationships ?? []
  if (rels.length === 0) {
    return (
      <Card className={cardClass}>
        <p className={sub}>This project has no relationships.</p>
      </Card>
    )
  }

  const outbound =
    filter === 'used-by' ? [] : rels.filter((r) => r.direction === 'outbound')
  const inbound =
    filter === 'uses' ? [] : rels.filter((r) => r.direction === 'inbound')

  return (
    <div className="flex gap-6">
      <RelationshipsSidebar
        outbound={outbound}
        inbound={inbound}
        filter={filter}
        onFilterChange={setFilter}
        isDarkMode={isDarkMode}
      />
      <div className="min-w-0 flex-1">
        <Card
          className={`overflow-hidden ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}
        >
          <RelationshipsGraph
            outbound={outbound}
            inbound={inbound}
            projectName={projectName}
            isDarkMode={isDarkMode}
          />
        </Card>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                           */
/* ------------------------------------------------------------------ */

interface RelationshipsSidebarProps {
  outbound: ProjectRelationship[]
  inbound: ProjectRelationship[]
  filter: RelationshipFilter
  onFilterChange: (f: RelationshipFilter) => void
  isDarkMode: boolean
}

function RelationshipsSidebar({
  outbound,
  inbound,
  filter,
  onFilterChange,
  isDarkMode,
}: RelationshipsSidebarProps) {
  const sectionLabel = isDarkMode ? 'text-gray-500' : 'text-slate-400'
  const sub = isDarkMode ? 'text-gray-400' : 'text-slate-500'

  const chipBase =
    'rounded-full px-3 py-1 text-xs font-medium transition-colors'
  const chipSelected = 'bg-amber-500 text-white'
  const chipUnselected = isDarkMode
    ? 'border border-gray-600 text-gray-300 hover:border-gray-400'
    : 'border border-slate-300 text-slate-600 hover:border-slate-400'

  return (
    <div
      className={`w-[240px] flex-shrink-0 rounded-lg border p-4 ${
        isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-slate-200 bg-white'
      }`}
    >
      {/* Filter chips */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {(['all', 'uses', 'used-by'] as const).map((f) => (
          <button
            key={f}
            onClick={() => onFilterChange(f)}
            className={`${chipBase} ${filter === f ? chipSelected : chipUnselected}`}
          >
            {f === 'all' ? 'All' : f === 'uses' ? 'Uses' : 'Used by'}
          </button>
        ))}
        <button
          disabled
          className={`${chipBase} flex items-center gap-1 opacity-50 ${chipUnselected}`}
        >
          <Plus className="h-3 w-3" />
          Add
        </button>
      </div>

      {/* Outbound (USES) section */}
      {filter !== 'used-by' && (
        <div className="mb-4">
          <h4
            className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] ${sectionLabel}`}
          >
            Uses
          </h4>
          {outbound.length === 0 ? (
            <p className={`text-xs ${sub}`}>No outbound relationships</p>
          ) : (
            <ul className="space-y-1">
              {outbound.map((r) => (
                <SidebarProjectRow
                  key={`out:${r.project.id}`}
                  rel={r}
                  isDarkMode={isDarkMode}
                />
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Inbound (USED BY) section */}
      {filter !== 'uses' && (
        <div>
          <h4
            className={`mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] ${sectionLabel}`}
          >
            Used by
          </h4>
          {inbound.length === 0 ? (
            <p className={`text-xs ${sub}`}>No inbound relationships</p>
          ) : (
            <ul className="space-y-1">
              {inbound.map((r) => (
                <SidebarProjectRow
                  key={`in:${r.project.id}`}
                  rel={r}
                  isDarkMode={isDarkMode}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function SidebarProjectRow({
  rel,
  isDarkMode,
}: {
  rel: ProjectRelationship
  isDarkMode: boolean
}) {
  const typeSlug = rel.project.project_type ?? ''
  const dotColor = typeSlug ? getTypeColor(typeSlug) : '#94a3b8'
  const muted = isDarkMode ? 'text-gray-500' : 'text-slate-400'

  return (
    <li className="flex items-center gap-2 py-1">
      <span
        className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-full"
        style={{ backgroundColor: dotColor }}
      />
      <Link
        to={`/projects/${rel.project.id}`}
        className={`truncate text-sm hover:underline ${
          isDarkMode ? 'text-amber-400' : 'text-amber-text'
        }`}
      >
        {rel.project.name}
      </Link>
      {typeSlug && (
        <span className={`flex-shrink-0 text-[10px] ${muted}`}>{typeSlug}</span>
      )}
    </li>
  )
}

/* ------------------------------------------------------------------ */
/*  Graph visualization                                               */
/* ------------------------------------------------------------------ */

interface RelationshipsGraphProps {
  outbound: ProjectRelationship[]
  inbound: ProjectRelationship[]
  projectName: string
  isDarkMode: boolean
}

/** Compute evenly-spaced Y positions centered around a midpoint. */
function computeYPositions(count: number, centerY: number): number[] {
  if (count === 0) return []
  const maxStep = 90
  const maxHeight = 320
  const step = Math.min(maxStep, maxHeight / Math.max(count, 1))
  const totalHeight = (count - 1) * step
  const startY = centerY - totalHeight / 2
  return Array.from({ length: count }, (_, i) => startY + i * step)
}

function truncateName(name: string, maxLen: number): string {
  return name.length > maxLen ? name.slice(0, maxLen) + '...' : name
}

function RelationshipsGraph({
  outbound,
  inbound,
  projectName,
  isDarkMode,
}: RelationshipsGraphProps) {
  const centerX = 360
  const centerY = 210
  const centerR = 40
  const neighborR = outbound.length > 5 || inbound.length > 5 ? 24 : 28
  const outX = 140
  const inX = 580

  const labelColor = isDarkMode ? '#64748b' : '#94a3b8'
  const lineColor = isDarkMode ? '#475569' : '#cbd5e1'
  const centerFill = '#f59e0b'
  const centerStroke = '#d97706'
  const centerTextColor = isDarkMode ? '#1c1917' : '#1c1917'
  const bgColor = isDarkMode ? '#1f2937' : '#ffffff'
  const belowTextColor = isDarkMode ? '#d1d5db' : '#334155'

  const outYs = computeYPositions(outbound.length, centerY)
  const inYs = computeYPositions(inbound.length, centerY)

  return (
    <svg
      viewBox="0 0 720 400"
      preserveAspectRatio="xMidYMid meet"
      className="w-full"
      style={{ backgroundColor: bgColor }}
    >
      {/* Section labels */}
      <text
        x={outX}
        y={36}
        textAnchor="middle"
        fill={labelColor}
        fontSize="10"
        letterSpacing="0.12em"
        fontWeight="600"
      >
        DEPENDS ON
      </text>
      <text
        x={inX}
        y={36}
        textAnchor="middle"
        fill={labelColor}
        fontSize="10"
        letterSpacing="0.12em"
        fontWeight="600"
      >
        DEPENDED ON BY
      </text>

      {/* Dashed connectors — outbound */}
      {outbound.map((r, i) => (
        <line
          key={`line-out-${r.project.id}`}
          x1={centerX}
          y1={centerY}
          x2={outX}
          y2={outYs[i]}
          stroke={lineColor}
          strokeDasharray="4 4"
          strokeWidth="1.5"
        />
      ))}

      {/* Dashed connectors — inbound */}
      {inbound.map((r, i) => (
        <line
          key={`line-in-${r.project.id}`}
          x1={centerX}
          y1={centerY}
          x2={inX}
          y2={inYs[i]}
          stroke={lineColor}
          strokeDasharray="4 4"
          strokeWidth="1.5"
        />
      ))}

      {/* Center node */}
      <circle
        cx={centerX}
        cy={centerY}
        r={centerR}
        fill={centerFill}
        stroke={centerStroke}
        strokeWidth="2"
      />
      <text
        x={centerX}
        y={centerY}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={centerTextColor}
        fontSize="10"
        fontWeight="600"
      >
        {truncateName(projectName, 10)}
      </text>

      {/* Outbound neighbor nodes */}
      {outbound.map((r, i) => (
        <NeighborNode
          key={`out-${r.project.id}`}
          rel={r}
          cx={outX}
          cy={outYs[i]}
          radius={neighborR}
          belowTextColor={belowTextColor}
          isDarkMode={isDarkMode}
        />
      ))}

      {/* Inbound neighbor nodes */}
      {inbound.map((r, i) => (
        <NeighborNode
          key={`in-${r.project.id}`}
          rel={r}
          cx={inX}
          cy={inYs[i]}
          radius={neighborR}
          belowTextColor={belowTextColor}
          isDarkMode={isDarkMode}
        />
      ))}
    </svg>
  )
}

function NeighborNode({
  rel,
  cx,
  cy,
  radius,
  belowTextColor,
}: {
  rel: ProjectRelationship
  cx: number
  cy: number
  radius: number
  belowTextColor: string
  isDarkMode: boolean
}) {
  const typeSlug = rel.project.project_type ?? ''
  const fill = typeSlug ? getTypeColor(typeSlug) : '#94a3b8'

  return (
    <Link to={`/projects/${rel.project.id}`} className="cursor-pointer">
      <g className="opacity-100 transition-opacity hover:opacity-80">
        <circle cx={cx} cy={cy} r={radius} fill={fill} />
        <text
          x={cx}
          y={cy + radius + 14}
          textAnchor="middle"
          fill={belowTextColor}
          fontSize="10"
        >
          {truncateName(rel.project.name, 16)}
        </text>
      </g>
    </Link>
  )
}

function PlaceholderTab({
  name,
  isDarkMode,
}: {
  name: string
  isDarkMode: boolean
}) {
  return (
    <Card className={`p-12 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}>
      <div className="text-center">
        <h3
          className={`mb-2 text-lg ${isDarkMode ? 'text-white' : 'text-slate-900'}`}
        >
          {name}
        </h3>
        <p className={isDarkMode ? 'text-gray-400' : 'text-slate-500'}>
          This tab will be implemented in a future update.
        </p>
      </div>
    </Card>
  )
}
