import {
  TrendingUp,
  TrendingDown,
  Settings2 as SettingsIcon,
  ArrowRight,
  Rocket,
} from 'lucide-react'
import { getIcon, useIconRegistryVersion } from '@/lib/icons'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import { LabelChip } from '@/components/ui/label-chip'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'
import { useCallback, useEffect, useMemo } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useOrganization } from '@/contexts/OrganizationContext'
import { sanitizeHttpUrl, sortEnvironments } from '@/lib/utils'
import {
  listLinkDefinitions,
  getProjectSchema,
  listProjectNotes,
  listTeams,
  listProjectTypes,
} from '@/api/endpoints'
import { OperationsLog } from '@/components/OperationsLog'
import type { Project } from '@/types'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { useProjectPatch } from '@/hooks/useProjectPatch'
import { ProjectRelationshipsTab } from '@/components/ProjectRelationshipsTab'
import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ProjectAttributesSection } from '@/components/ProjectAttributesSection'
import { ProjectSettingsTab } from '@/components/ProjectSettingsTab'
import { ProjectNotesTab } from '@/components/notes/ProjectNotesTab'

interface ProjectDetailProps {
  project: Project
  initialTab?: string
  initialSubId?: string
  initialSubAction?: string
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

export function ProjectDetail({
  project,
  initialTab,
  initialSubId,
  initialSubAction,
}: ProjectDetailProps) {
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

  // Mock data for aspects not yet available from the API. Dev-only so
  // production builds don't leak hardcoded placeholder content.
  const isDev = import.meta.env.DEV
  const healthScore = isDev ? 66 : null
  const healthTrend = isDev ? 'down' : null

  const deploymentStatus: Record<
    string,
    { version: string; status: string; updated: string }
  > = isDev
    ? {
        'infrastructure-testing': {
          version: '1962b02',
          status: 'success',
          updated: '2m ago',
        },
        testing: { version: '1962b02', status: 'success', updated: '2m ago' },
        staging: { version: '1.0.11', status: 'success', updated: '1h ago' },
        production: { version: '1.0.10', status: 'success', updated: '3h ago' },
      }
    : {}

  const feed = isDev
    ? [
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
    : []

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: linkDefs = [] } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    enabled: !!orgSlug,
  })

  const { data: projectSchema } = useQuery({
    queryKey: ['projectSchema', orgSlug, project.id],
    queryFn: ({ signal }) => getProjectSchema(orgSlug, project.id, signal),
    enabled: !!orgSlug,
  })

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    enabled: !!orgSlug,
  })
  const { data: projectTypes = [] } = useQuery({
    queryKey: ['projectTypes', orgSlug],
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    enabled: !!orgSlug,
  })
  const { data: projectNotes = [] } = useQuery({
    queryKey: ['projectNotes', orgSlug, project.id],
    queryFn: ({ signal }) =>
      listProjectNotes(orgSlug, project.id, undefined, signal),
    enabled: !!orgSlug && !!project.id,
  })

  // Bumps when an icon-set chunk finishes loading; include in useMemo deps
  // where icons are resolved so they refresh once available.
  const iconRegistryVersion = useIconRegistryVersion()

  const linkDefMap = useMemo(
    () => Object.fromEntries(linkDefs.map((ld) => [ld.slug, ld])),
    [linkDefs],
  )

  const externalLinks = useMemo(
    () =>
      Object.entries(project.links || {})
        .map(([key, url]) => {
          const safeUrl = sanitizeHttpUrl(url)
          if (!safeUrl) return null
          const def = linkDefMap[key]
          return {
            key,
            url: safeUrl,
            Icon: getIcon(def?.icon),
            label: def?.name || key.replace(/_/g, ' '),
          }
        })
        .filter((link): link is NonNullable<typeof link> => link !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project.links, linkDefMap, iconRegistryVersion],
  )

  const teamOptions = useMemo(
    () => teams.map((t) => ({ value: t.slug, label: t.name })),
    [teams],
  )

  const projectTypeOptions = useMemo(
    () => projectTypes.map((pt) => ({ value: pt.slug, label: pt.name })),
    [projectTypes],
  )

  const label = 'text-tertiary'
  const value = 'text-primary'
  const muted = 'text-tertiary'
  const divider = 'border-tertiary'

  const handleCommitName = useCallback(
    (v: string | null) => patch('/name', v ?? ''),
    [patch],
  )
  const handleCommitDescription = useCallback(
    (v: string | null) => patch('/description', v),
    [patch],
  )
  const handleCommitTeamSlug = useCallback(
    (v: string) => patch('/team_slug', v),
    [patch],
  )
  const handleCommitSlug = useCallback(
    (v: string | null) => patch('/slug', v ?? ''),
    [patch],
  )
  const handleCommitProjectTypeSlugs = useCallback(
    (v: string[]) => patch('/project_type_slugs', v),
    [patch],
  )

  const renderNameValue = useCallback(
    (v: string) => <span className={`text-[1.75rem] ${value}`}>{v}</span>,
    [value],
  )
  const renderSlugValue = useCallback(
    (v: string) => <span className={`font-mono text-sm ${value}`}>{v}</span>,
    [value],
  )

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'configuration', label: 'Configuration' },
    { id: 'dependencies', label: 'Dependencies' },
    { id: 'logs', label: 'Logs' },
    {
      id: 'notes',
      label:
        projectNotes.length > 0 ? `Notes (${projectNotes.length})` : 'Notes',
    },
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

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      {/* Project Header */}
      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="-ml-[18px] mb-1 flex items-center gap-3">
              <InlineText
                value={project.name}
                onCommit={handleCommitName}
                pending={pendingPath === '/name'}
                className="text-[1.75rem]"
                renderValue={renderNameValue}
              />
            </div>
          </div>

          {/* Deployment Pipeline (mocked, dev only) */}
          {isDev && (
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
          )}
        </div>

        <div className="-ml-[18px] mt-3 text-secondary">
          <InlineTextarea
            value={project.description ?? null}
            onCommit={handleCommitDescription}
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
                  {index > 0 && <span className="mr-1.5 text-tertiary">|</span>}
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
          {tabs.map((tab) =>
            tab.id === 'settings' ? (
              <TooltipProvider key={tab.id} delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <TabsTrigger
                      value={tab.id}
                      aria-label="Project Settings"
                      className="ml-auto"
                    >
                      <SettingsIcon className="h-4 w-4" />
                    </TabsTrigger>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Project Settings</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.label}
              </TabsTrigger>
            ),
          )}
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
                        options={teamOptions}
                        onCommit={handleCommitTeamSlug}
                        pending={pendingPath === '/team_slug'}
                      />
                    </div>

                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Slug</span>
                      <InlineText
                        value={project.slug}
                        onCommit={handleCommitSlug}
                        pending={pendingPath === '/slug'}
                        renderValue={renderSlugValue}
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
                        options={projectTypeOptions}
                        onCommit={handleCommitProjectTypeSlugs}
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

                    <ProjectAttributesSection
                      project={project}
                      projectSchema={projectSchema}
                      patch={patch}
                      pendingPath={pendingPath}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Environments */}
              {sortedEnvironments.length > 0 && (
                <ProjectEnvironmentsCard
                  environments={sortedEnvironments}
                  deploymentStatus={deploymentStatus}
                />
              )}
            </div>

            {/* Right column: Health & Compliance + Recent Activity (dev only) */}
            {isDev && (
              <div className="space-y-6">
                {/* Health & Compliance (mocked, dev only) */}
                <Card>
                  <CardHeader>
                    <CardTitle>Health &amp; compliance</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="mb-4 flex items-center gap-3">
                      <div
                        className={`flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-lg text-2xl font-medium ${
                          (healthScore ?? 0) >= 90
                            ? 'bg-green-50 text-green-700'
                            : (healthScore ?? 0) >= 80
                              ? 'bg-emerald-50 text-emerald-700'
                              : (healthScore ?? 0) >= 70
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

                {/* Recent Activity (mocked, dev only) */}
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
                              <span className="font-mono text-xs text-tertiary">
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
            )}
          </div>
        </TabsContent>

        <TabsContent value="configuration">
          <PlaceholderTab name="Configuration" />
        </TabsContent>
        <TabsContent value="relationships">
          <ProjectRelationshipsTab
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
          <ProjectNotesTab
            orgSlug={project.team.organization.slug}
            projectId={project.id}
            projectTypeSlugs={
              project.project_types && project.project_types.length > 0
                ? project.project_types.map((pt) => pt.slug)
                : project.project_type
                  ? [project.project_type.slug]
                  : []
            }
            initialNoteId={activeTab === 'notes' ? initialSubId : undefined}
            initialAction={activeTab === 'notes' ? initialSubAction : undefined}
          />
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
          <ProjectSettingsTab project={project} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function PlaceholderTab({ name }: { name: string }) {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <CardTitle>{name}</CardTitle>
        <CardDescription className="text-tertiary">
          This tab will be implemented in a future update.
        </CardDescription>
      </CardContent>
    </Card>
  )
}
