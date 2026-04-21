import {
  ExternalLink,
  TrendingUp,
  TrendingDown,
  Settings as SettingsIcon,
  ArrowRight,
  Rocket,
} from 'lucide-react'
import { getIcon } from '@/lib/icons'
import { resolveColor, resolveIcon } from '@/lib/ui-maps'
import type { XUiMaps } from '@/lib/ui-maps'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { LabelChip } from '@/components/ui/label-chip'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'
import { useEffect, useMemo, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useOrganization } from '@/contexts/OrganizationContext'
import { ApiError } from '@/api/client'
import { sortEnvironments } from '@/lib/utils'
import {
  listLinkDefinitions,
  listEnvironments,
  getProjectSchema,
  getProjectRelationships,
  patchProject,
  deleteProject,
  listTeams,
  listProjectTypes,
} from '@/api/endpoints'
import { OperationsLog } from '@/components/OperationsLog'
import { buildRelationshipEdges } from '@/lib/relationship-edges'
import type {
  ProjectSchemaSection,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import {
  isFieldEditable,
  pickInlineComponent,
} from '@/components/ui/inline-edit/field-policy'
import { InlineSwitch } from '@/components/ui/inline-edit/InlineSwitch'
import { InlineNumber } from '@/components/ui/inline-edit/InlineNumber'
import { InlineDate } from '@/components/ui/inline-edit/InlineDate'
import {
  ProjectsGraphCanvas,
  type GraphProject,
} from '@/components/ProjectsGraphCanvas'
import { EditRelationshipsDialog } from '@/components/EditRelationshipsDialog'
import { EditIdentifiersCard } from '@/components/EditIdentifiersCard'
import { EditLinksCard } from '@/components/EditLinksCard'
import { EditEnvironmentsCard } from '@/components/EditEnvironmentsCard'
import type { Project, ProjectRelationship } from '@/types'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { useProjectPatch } from '@/hooks/useProjectPatch'

interface ProjectDetailProps {
  project: Project
  initialTab?: string
}

const VALID_TABS = [
  'overview',
  'configuration',
  'dependencies',
  'relationships',
  'logs',
  'notes',
  'operations-log',
  'settings',
] as const

type TabType = (typeof VALID_TABS)[number]

const VALID_TAB_SET: Set<string> = new Set(VALID_TABS)

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

export function ProjectDetail({ project, initialTab }: ProjectDetailProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const { patch, pendingPath } = useProjectPatch(orgSlug, project.id)
  const navigate = useNavigate()

  const activeTab: TabType =
    initialTab && VALID_TAB_SET.has(initialTab)
      ? (initialTab as TabType)
      : 'overview'

  const handleTabChange = (value: string) => {
    const path =
      value === 'overview'
        ? `/projects/${project.id}`
        : `/projects/${project.id}/${value}`
    navigate(path, { replace: true })
  }

  // Redirect to clean URL when the tab slug is invalid
  useEffect(() => {
    if (initialTab && !VALID_TAB_SET.has(initialTab)) {
      navigate(`/projects/${project.id}`, { replace: true })
    }
  }, [initialTab, navigate, project.id])

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
    () => sortEnvironments(project.environments || []),
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

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: () => listTeams(orgSlug),
    enabled: !!orgSlug,
  })
  const { data: projectTypes = [] } = useQuery({
    queryKey: ['projectTypes', orgSlug],
    queryFn: () => listProjectTypes(orgSlug),
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
      def: ProjectSchemaSectionProperty
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
          def,
        })
      }
    }
    return fields.sort((a, b) => a.label.localeCompare(b.label))
  }, [projectSchema, project])

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'configuration', label: 'Configuration' },
    { id: 'dependencies', label: 'Dependencies' },
    { id: 'logs', label: 'Logs' },
    { id: 'notes', label: 'Notes' },
    { id: 'operations-log', label: 'Operations Log' },
    {
      id: 'relationships',
      label: (() => {
        const rel = project.relationships
        const total = (rel?.inbound_count ?? 0) + (rel?.outbound_count ?? 0)
        return `Relationships (${total})`
      })(),
    },
    { id: 'settings', label: '' },
  ]

  const label = 'text-tertiary'
  const value = 'text-primary'
  const muted = 'text-tertiary'
  const divider = 'border-tertiary'

  function renderInlineForField(
    _key: string,
    def: ProjectSchemaSectionProperty,
    raw: unknown,
    onCommit: (v: unknown) => Promise<void>,
    pending: boolean,
    display: React.ReactNode,
  ): React.ReactNode {
    const kind = pickInlineComponent(def)
    switch (kind) {
      case 'select':
        return (
          <InlineSelect
            value={raw == null ? null : String(raw)}
            options={(def.enum ?? []).map((v) => ({
              value: String(v),
              label: String(v),
            }))}
            onCommit={(v) => onCommit(v)}
            pending={pending}
            renderDisplay={display}
          />
        )
      case 'switch':
        return (
          <InlineSwitch
            value={raw === true || raw === 'true'}
            onCommit={(v) => onCommit(v)}
            pending={pending}
          />
        )
      case 'number':
        return (
          <InlineNumber
            value={raw == null || raw === '' ? null : Number(raw)}
            integer={def.type === 'integer'}
            min={def.minimum ?? undefined}
            max={def.maximum ?? undefined}
            onCommit={(v) => onCommit(v)}
            pending={pending}
            renderDisplay={display}
          />
        )
      case 'date':
        return (
          <InlineDate
            value={raw == null ? null : String(raw)}
            mode={def.format === 'date-time' ? 'date-time' : 'date'}
            onCommit={(v) => onCommit(v)}
            pending={pending}
            renderDisplay={display}
          />
        )
      default:
        return (
          <InlineText
            value={raw == null ? null : String(raw)}
            onCommit={(v) => onCommit(v)}
            pending={pending}
            renderValue={display !== null ? () => display : undefined}
          />
        )
    }
  }

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      {/* Project Header */}
      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="-ml-[18px] mb-1 flex items-center gap-3">
              <InlineText
                value={project.name}
                onCommit={(v) => patch('/name', v ?? '')}
                pending={pendingPath === '/name'}
                className="text-[1.75rem]"
                renderValue={(v) => (
                  <span className={`text-[1.75rem] ${value}`}>{v}</span>
                )}
              />
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
                      <ArrowRight className="h-4 w-4 text-tertiary" />
                    )}
                    {color ? (
                      <LabelChip
                        hex={color}
                        className="rounded-md px-3 py-1.5 text-sm"
                      >
                        {env.name}: {deployment.version}
                      </LabelChip>
                    ) : (
                      <span className="inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium">
                        {env.name}: {deployment.version}
                      </span>
                    )}
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

        <div className="-ml-[18px] mt-3 text-secondary">
          <InlineTextarea
            value={project.description ?? null}
            onCommit={(v) => patch('/description', v)}
            pending={pendingPath === '/description'}
            placeholder="Add a description…"
            rows={2}
          />
        </div>

        {/* External Links */}
        {externalLinks.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {externalLinks.map(
              ({ key, url, Icon, label: linkLabel }, index) => (
                <span key={key} className="flex items-center gap-1.5">
                  {index > 0 && (
                    <span className={'mr-1.5 text-tertiary'}>|</span>
                  )}
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={
                      'flex items-center gap-1.5 text-sm text-warning hover:underline'
                    }
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
      <Tabs value={activeTab} onValueChange={handleTabChange}>
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
              <Card>
                <CardHeader>
                  <CardTitle>Project details</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-0">
                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Team</span>
                      <InlineSelect
                        value={project.team.slug}
                        options={teams.map((t) => ({
                          value: t.slug,
                          label: t.name,
                        }))}
                        onCommit={(v) => patch('/team_slug', v)}
                        pending={pendingPath === '/team_slug'}
                      />
                    </div>

                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Slug</span>
                      <InlineText
                        value={project.slug}
                        onCommit={(v) => patch('/slug', v ?? '')}
                        pending={pendingPath === '/slug'}
                        renderValue={(v) => (
                          <span className={`font-mono text-sm ${value}`}>
                            {v}
                          </span>
                        )}
                      />
                    </div>

                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Project types</span>
                      <InlineMultiSelect
                        values={(project.project_types || []).map(
                          (pt) => pt.slug,
                        )}
                        options={projectTypes.map((pt) => ({
                          value: pt.slug,
                          label: pt.name,
                        }))}
                        onCommit={(v) => patch('/project_type_slugs', v)}
                        pending={pendingPath === '/project_type_slugs'}
                      />
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

                    {attributeFields.map(
                      ({
                        key,
                        label: fieldLabel,
                        value: fieldValue,
                        rawValue,
                        title: fieldTitle,
                        uiMaps,
                        def,
                      }) => {
                        const mappedColor = resolveColor(uiMaps, rawValue)
                        const mappedIcon = resolveIcon(uiMaps, rawValue)
                        const FieldIcon = mappedIcon
                          ? getIcon(mappedIcon)
                          : null
                        const textColorClass = mappedColor
                          ? (COLOR_TEXT[mappedColor] ?? value)
                          : value
                        const editable = isFieldEditable(key, def)
                        const richDisplay =
                          fieldValue !== null ? (
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
                          ) : null
                        return (
                          <div
                            key={key}
                            className={`flex items-center justify-between border-b py-1.5 ${divider} last:border-0`}
                          >
                            <span className={`text-sm ${label}`}>
                              {fieldLabel}
                            </span>
                            {editable ? (
                              renderInlineForField(
                                key,
                                def,
                                rawValue,
                                (v) => patch(`/${key}`, v),
                                pendingPath === `/${key}`,
                                richDisplay,
                              )
                            ) : richDisplay !== null ? (
                              richDisplay
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
                </CardContent>
              </Card>

              {/* Environments */}
              {sortedEnvironments.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Environments</CardTitle>
                  </CardHeader>
                  <CardContent>
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
                        const deployment = deploymentStatus[env.slug]
                        return (
                          <div
                            key={env.slug}
                            className={`flex items-center border-b py-2 ${divider} last:border-0`}
                          >
                            <div className="w-32 flex-shrink-0">
                              <EnvironmentBadge
                                name={env.name}
                                slug={env.slug}
                                label_color={env.label_color}
                              />
                            </div>
                            <div className="flex-1 text-center">
                              <span
                                className={'font-mono text-sm text-tertiary'}
                              >
                                {deployment?.version ?? ''}
                              </span>
                            </div>
                            <div className="flex-1 text-right">
                              {url ? (
                                <a
                                  href={url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={
                                    'inline-flex items-center gap-1.5 text-sm text-warning hover:underline'
                                  }
                                >
                                  {url}
                                  <ExternalLink
                                    className={'h-3 w-3 text-warning'}
                                  />
                                </a>
                              ) : (
                                <span className={`text-sm ${muted}`}>
                                  &mdash;
                                </span>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right column: Health & Compliance + Recent Activity */}
            <div className="space-y-6">
              {/* Health & Compliance */}
              <Card>
                <CardHeader>
                  <CardTitle>Health &amp; compliance</CardTitle>
                </CardHeader>
                <CardContent>
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
                </CardContent>
              </Card>

              {/* Recent Activity (mocked) */}
              <Card>
                <CardHeader>
                  <CardTitle>Recent activity</CardTitle>
                </CardHeader>
                <CardContent>
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
                            <span className={'font-mono text-xs text-tertiary'}>
                              {item.version}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="configuration">
          <PlaceholderTab name="Configuration" />
        </TabsContent>
        <TabsContent value="relationships">
          <RelationshipsTab
            orgSlug={project.team.organization.slug}
            projectId={project.id}
            project={project}
          />
        </TabsContent>
        <TabsContent value="dependencies">
          <PlaceholderTab name="Dependencies" />
        </TabsContent>
        <TabsContent value="logs">
          <PlaceholderTab name="Logs" />
        </TabsContent>
        <TabsContent value="notes">
          <PlaceholderTab name="Notes" />
        </TabsContent>
        <TabsContent value="operations-log">
          <OperationsLog
            projectSlug={project.slug}
            showSummary={false}
            showHeader={false}
            embedded
          />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab project={project} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

type RelFilter = 'all' | 'uses' | 'used-by'

function RelationshipsTab({
  orgSlug,
  projectId,
  project,
}: {
  orgSlug: string
  projectId: string
  project: Project
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['project-relationships', orgSlug, projectId],
    queryFn: () => getProjectRelationships(orgSlug, projectId),
  })
  const [filter, setFilter] = useState<RelFilter>('all')
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  const sub = 'text-tertiary'

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <p className={sub}>Loading relationships…</p>
        </CardContent>
      </Card>
    )
  }
  if (isError && !data) {
    return (
      <Card>
        <CardContent>
          <p className={sub}>Failed to load relationships.</p>
        </CardContent>
      </Card>
    )
  }

  const rels = data?.relationships ?? []

  const outbound = rels.filter((r) => r.direction === 'outbound')
  const inbound = rels.filter((r) => r.direction === 'inbound')
  const outboundVisible = filter !== 'used-by'
  const inboundVisible = filter !== 'uses'
  const visibleOutbound = outboundVisible ? outbound : []
  const visibleInbound = inboundVisible ? inbound : []

  // Build projects and edges for the shared canvas, filtered by visibility.
  // Deduplicate: a related project can appear in both inbound and outbound.
  const visibleRels = [...visibleOutbound, ...visibleInbound]
  const projects: GraphProject[] = Array.from(
    new Map<string, GraphProject>([
      [
        project.id,
        {
          id: project.id,
          name: project.name,
          project_types: project.project_types?.map((pt) => ({
            slug: pt.slug,
            icon: pt.icon ?? null,
          })),
        },
      ],
      ...visibleRels.map(
        (r) =>
          [
            r.project.id,
            {
              id: r.project.id,
              name: r.project.name,
              project_types: r.project.project_type
                ? [
                    {
                      slug: r.project.project_type,
                      icon: r.project.project_type_icon ?? null,
                    },
                  ]
                : [],
            },
          ] as [string, GraphProject],
      ),
    ]).values(),
  )

  const edges = Array.from(
    new Map(
      buildRelationshipEdges(projectId, visibleRels).map((edge) => [
        edge.id,
        edge,
      ]),
    ).values(),
  )

  return (
    <>
      {rels.length === 0 ? (
        <Card>
          <CardContent className="flex items-center justify-between">
            <p className={sub}>This project has no relationships.</p>
            <Button
              size="sm"
              className="gap-1 bg-action text-action-foreground hover:bg-action-hover"
              onClick={() => setEditDialogOpen(true)}
            >
              Edit
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div
          className="grid min-h-[24rem] grid-cols-1 gap-6 lg:grid-cols-[400px_1fr]"
          style={{
            height: 'calc(100vh - 22rem - var(--assistant-height, 4rem))',
          }}
        >
          <RelationshipsSidebar
            outbound={outbound}
            inbound={inbound}
            outboundVisible={outboundVisible}
            inboundVisible={inboundVisible}
            filter={filter}
            onFilterChange={setFilter}
            onAdd={() => setEditDialogOpen(true)}
          />
          <ProjectsGraphCanvas
            projects={projects}
            edges={edges}
            centerId={projectId}
          />
        </div>
      )}
      <EditRelationshipsDialog
        isOpen={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        projectId={projectId}
        projectName={project.name}
        relationships={rels}
      />
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                           */
/* ------------------------------------------------------------------ */

interface RelationshipsSidebarProps {
  outbound: ProjectRelationship[]
  inbound: ProjectRelationship[]
  outboundVisible: boolean
  inboundVisible: boolean
  filter: RelFilter
  onFilterChange: (f: RelFilter) => void
  onAdd: () => void
}

function RelationshipsSidebar({
  outbound,
  inbound,
  outboundVisible,
  inboundVisible,
  filter,
  onFilterChange,
  onAdd,
}: RelationshipsSidebarProps) {
  const sectionLabel = 'text-tertiary'
  const sub = 'text-tertiary'

  const chipBase =
    'rounded-full px-3 py-1 text-xs font-medium transition-colors'
  const chipSelected = 'bg-amber-500 text-white'
  const chipUnselected =
    'border border-input text-secondary hover:border-secondary'

  return (
    <Card
      className={`h-full min-h-0 w-full flex-shrink-0 overflow-y-auto ${''}`}
    >
      <CardHeader className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-1.5">
            {(['all', 'uses', 'used-by'] as const).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={filter === f}
                onClick={() => onFilterChange(f)}
                className={`${chipBase} ${filter === f ? chipSelected : chipUnselected}`}
              >
                {f === 'all' ? 'All' : f === 'uses' ? 'Uses' : 'Used by'}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="sm" onClick={onAdd}>
            Edit
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-4 pt-2">
        {/* Outbound (USES) section */}
        {outboundVisible && (
          <div className="mb-4">
            <h4
              className={`mb-2 text-[10px] font-medium uppercase tracking-[0.12em] ${sectionLabel}`}
            >
              Uses
            </h4>
            {outbound.length === 0 ? (
              <p className={`text-xs ${sub}`}>None</p>
            ) : (
              <ul className="space-y-1">
                {outbound.map((r, i) => (
                  <SidebarProjectRow key={`out:${r.project.id}:${i}`} rel={r} />
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Inbound (USED BY) section */}
        {inboundVisible && (
          <div>
            <h4
              className={`mb-2 text-[10px] font-medium uppercase tracking-[0.12em] ${sectionLabel}`}
            >
              Used by
            </h4>
            {inbound.length === 0 ? (
              <p className={`text-xs ${sub}`}>None</p>
            ) : (
              <ul className="space-y-1">
                {inbound.map((r, i) => (
                  <SidebarProjectRow key={`in:${r.project.id}:${i}`} rel={r} />
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SidebarProjectRow({ rel }: { rel: ProjectRelationship }) {
  const typeSlug = rel.project.project_type ?? ''
  const muted = 'text-tertiary'

  return (
    <li className="flex items-center gap-2 py-1">
      <Link
        to={`/projects/${rel.project.id}`}
        className={`truncate text-sm hover:underline ${'text-warning'}`}
      >
        {rel.project.name}
      </Link>
      {typeSlug && (
        <span className={`flex-shrink-0 text-[10px] ${muted}`}>{typeSlug}</span>
      )}
    </li>
  )
}

function SettingsTab({ project }: { project: Project }) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { patch } = useProjectPatch(orgSlug, project.id)
  const [deleteConfirmSlug, setDeleteConfirmSlug] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const invalidateProject = () => {
    queryClient.invalidateQueries({
      queryKey: ['project', orgSlug, project.id],
    })
  }

  const mutationErrorHandler = (label: string) => {
    return (error: ApiError<{ detail?: string }> | Error) => {
      const detail =
        error instanceof ApiError
          ? error.response?.data?.detail || error.message
          : error.message
      alert(`Failed to ${label}: ${detail}`)
    }
  }

  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(orgSlug, project.id),
    onSuccess: () => navigate('/'),
    onError: mutationErrorHandler('delete project'),
  })

  const {
    data: linkDefs = [],
    isLoading: linkDefsLoading,
    isError: linkDefsError,
  } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: () => listLinkDefinitions(orgSlug),
    enabled: !!orgSlug,
  })

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: availableEnvironments = [] } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: () => listEnvironments(orgSlug),
    enabled: !!orgSlug,
  })

  return (
    <div className="space-y-6">
      {linkDefsLoading && (
        <Card>
          <CardContent>
            <p className={'text-sm text-tertiary'}>
              Loading link definitions...
            </p>
          </CardContent>
        </Card>
      )}
      {linkDefsError && (
        <Card>
          <CardContent>
            <p className="text-sm text-red-600 dark:text-red-400">
              Failed to load link definitions.
            </p>
          </CardContent>
        </Card>
      )}
      {!linkDefsLoading && !linkDefsError && linkDefs.length > 0 && (
        <EditLinksCard
          linkDefs={linkDefs}
          links={project.links || {}}
          onPatch={(entries) => patch('/links', entries)}
        />
      )}

      <EditEnvironmentsCard
        environments={sortedEnvironments}
        availableEnvironments={availableEnvironments}
        onPatch={async (envData) => {
          try {
            await patchProject(orgSlug, project.id, [
              { op: 'replace', path: '/environments', value: envData },
            ])
          } catch (error) {
            const detail =
              error instanceof ApiError
                ? (error.response as { data?: { detail?: string } } | undefined)
                    ?.data?.detail || error.message
                : error instanceof Error
                  ? error.message
                  : 'Failed to save'
            toast.error(`Save failed: ${detail}`)
            throw error
          }
          invalidateProject()
        }}
      />

      <EditIdentifiersCard
        identifiers={project.identifiers || {}}
        onPatch={(entries) => patch('/identifiers', entries)}
      />

      <Card className={'border-amber-300'}>
        <CardHeader>
          <CardTitle>Archive project</CardTitle>
          <CardDescription className={'text-secondary'}>
            Archiving the project will make it entirely read only. It will be
            hidden from the dashboard, won&apos;t show up in searches, and will
            be disabled as a dependency for any other projects that are
            dependent upon it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" size="sm" disabled>
            Archive project
          </Button>
        </CardContent>
      </Card>

      <Card className={'border-red-300'}>
        <CardHeader>
          <CardTitle>Delete project</CardTitle>
          <CardDescription className={'text-secondary'}>
            This action will <strong>permanently delete</strong>{' '}
            <code
              className={
                'rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-primary'
              }
            >
              {project.slug}
            </code>{' '}
            immediately, removing the project and all associated data, including
            facts, operation logs, and notes. Are you absolutely sure?
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!showDeleteConfirm ? (
            <Button
              variant="outline"
              size="sm"
              className={'border-danger bg-red-700 text-white hover:bg-red-800'}
              onClick={() => setShowDeleteConfirm(true)}
              disabled={!project.id}
            >
              Delete Project
            </Button>
          ) : (
            <div className="space-y-3">
              <p className={'text-sm text-secondary'}>
                Type{' '}
                <code
                  className={
                    'rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-primary'
                  }
                >
                  {project.slug}
                </code>{' '}
                to confirm deletion:
              </p>
              <Input
                value={deleteConfirmSlug}
                onChange={(e) => setDeleteConfirmSlug(e.target.value)}
                placeholder={project.slug}
                disabled={deleteMutation.isPending}
                className={''}
              />
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className={
                    'border-danger bg-red-700 text-white hover:bg-red-800'
                  }
                  onClick={() => deleteMutation.mutate()}
                  disabled={
                    deleteConfirmSlug !== project.slug ||
                    deleteMutation.isPending
                  }
                >
                  {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowDeleteConfirm(false)
                    setDeleteConfirmSlug('')
                  }}
                  disabled={deleteMutation.isPending}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PlaceholderTab({ name }: { name: string }) {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <CardTitle>{name}</CardTitle>
        <CardDescription className={'text-tertiary'}>
          This tab will be implemented in a future update.
        </CardDescription>
      </CardContent>
    </Card>
  )
}
