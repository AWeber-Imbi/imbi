import { useCallback, useEffect, useMemo } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  ArrowRight,
  Rocket,
  Settings2 as SettingsIcon,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

import {
  getProjectSchema,
  listCurrentReleases,
  listLinkDefinitions,
  listProjectNotes,
  listProjectTypes,
  listTeams,
} from '@/api/endpoints'
import { ProjectNotesTab } from '@/components/notes/ProjectNotesTab'
import { OperationsLog } from '@/components/OperationsLog'
import { ProjectAttributesSection } from '@/components/ProjectAttributesSection'
import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ProjectRelationshipsTab } from '@/components/ProjectRelationshipsTab'
import { ProjectSettingsTab } from '@/components/ProjectSettingsTab'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { LabelChip } from '@/components/ui/label-chip'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useProjectPatch } from '@/hooks/useProjectPatch'
import { getIcon, useIconRegistryVersion } from '@/lib/icons'
import { sanitizeHttpUrl, sortEnvironments } from '@/lib/utils'
import type { Project } from '@/types'

interface ProjectDetailProps {
  initialSubAction?: string
  initialSubId?: string
  initialTab?: string
  project: Project
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
  initialSubAction,
  initialSubId,
  initialTab,
  project,
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

  const { data: currentReleases = [] } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, project.id, signal),
    queryKey: ['currentReleases', orgSlug, project.id],
  })

  const deploymentStatus: Record<
    string,
    { status: string; updated: string; version: string }
  > = useMemo(() => {
    const out: Record<
      string,
      { status: string; updated: string; version: string }
    > = {}
    for (const row of currentReleases) {
      if (!row.release || !row.last_event_at) continue
      out[row.environment.slug] = {
        status: row.current_status ?? '',
        updated: formatDistanceToNow(new Date(row.last_event_at), {
          addSuffix: true,
        }),
        version: row.release.version,
      }
    }
    return out
  }, [currentReleases])

  const feed = isDev
    ? [
        {
          action: 'deployed in',
          environment: 'Testing',
          time: 'Nov 22, 2025, 12:28 PM',
          user: 'Scott Miller',
          version: '(1962b02)',
        },
        {
          action: 'deployed in',
          environment: 'Production',
          time: 'Nov 21, 2025, 4:09 PM',
          user: 'Scott Miller',
          version: '(1.0.11)',
        },
        {
          action: 'deployed in',
          environment: 'Staging',
          time: 'Nov 21, 2025, 4:08 PM',
          user: 'Scott Miller',
          version: '(1.0.11)',
        },
        {
          action: 'deployed in',
          environment: 'Testing',
          time: 'Nov 21, 2025, 4:08 PM',
          user: 'Scott Miller',
          version: '(d504611)',
        },
        {
          action: 'deployed in',
          environment: 'Production',
          time: 'Nov 21, 2025, 3:50 PM',
          user: 'Scott Miller',
          version: '(1.0.10)',
        },
        {
          action: 'deployed in',
          environment: 'Testing',
          time: 'Nov 21, 2025, 3:45 PM',
          user: 'Scott Miller',
          version: '(089f7fd)',
        },
      ]
    : []

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: linkDefs = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    queryKey: ['linkDefinitions', orgSlug],
  })

  const { data: projectSchema } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjectSchema(orgSlug, project.id, signal),
    queryKey: ['projectSchema', orgSlug, project.id],
  })

  const { data: teams = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
  })
  const { data: projectTypes = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: ['projectTypes', orgSlug],
  })
  const { data: projectNotes = [] } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) =>
      listProjectNotes(orgSlug, project.id, undefined, signal),
    queryKey: ['projectNotes', orgSlug, project.id],
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
            Icon: getIcon(def?.icon),
            key,
            label: def?.name || key.replace(/_/g, ' '),
            url: safeUrl,
          }
        })
        .filter((link): link is NonNullable<typeof link> => link !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project.links, linkDefMap, iconRegistryVersion],
  )

  const teamOptions = useMemo(
    () => teams.map((t) => ({ label: t.name, value: t.slug })),
    [teams],
  )

  const projectTypeOptions = useMemo(
    () => projectTypes.map((pt) => ({ label: pt.name, value: pt.slug })),
    [projectTypes],
  )

  const label = 'text-tertiary'
  const value = 'text-primary'
  const muted = 'text-tertiary'
  const divider = 'border-tertiary'

  const handleCommitName = useCallback(
    (v: null | string) => patch('/name', v ?? ''),
    [patch],
  )
  const handleCommitDescription = useCallback(
    (v: null | string) => patch('/description', v),
    [patch],
  )
  const handleCommitTeamSlug = useCallback(
    (v: string) => patch('/team_slug', v),
    [patch],
  )
  const handleCommitSlug = useCallback(
    (v: null | string) => patch('/slug', v ?? ''),
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
                className="text-[1.75rem]"
                onCommit={handleCommitName}
                pending={pendingPath === '/name'}
                renderValue={renderNameValue}
                value={project.name}
              />
            </div>
          </div>

          {/* Deployment Pipeline */}
          {Object.keys(deploymentStatus).length > 0 && (
            <div className="flex items-center gap-2">
              {sortedEnvironments
                .filter((env) => !!deploymentStatus[env.slug])
                .map((env, idx) => {
                  const deployment = deploymentStatus[env.slug]
                  const color = env.label_color
                  return (
                    <span className="contents" key={env.slug}>
                      {idx > 0 && (
                        <ArrowRight className="h-4 w-4 text-tertiary" />
                      )}
                      {color ? (
                        <LabelChip
                          className="rounded-md px-3 py-1.5 text-sm"
                          hex={color}
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
              {isDev && (
                <Button
                  className="ml-4 border-amber-400 bg-amber-50 text-amber-800 hover:bg-amber-100"
                  size="sm"
                  variant="outline"
                >
                  <Rocket className="mr-1 h-4 w-4" />
                  Deploy
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="-ml-[18px] mt-3 text-secondary">
          <InlineTextarea
            onCommit={handleCommitDescription}
            pending={pendingPath === '/description'}
            placeholder="Add a description…"
            rows={2}
            value={project.description ?? null}
          />
        </div>

        {/* External Links */}
        {externalLinks.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {externalLinks.map(
              ({ Icon, key, label: linkLabel, url }, index) => (
                <span className="flex items-center gap-1.5" key={key}>
                  {index > 0 && <span className="mr-1.5 text-tertiary">|</span>}
                  <a
                    className={
                      'flex items-center gap-1.5 text-sm text-warning hover:underline'
                    }
                    href={url}
                    rel="noopener noreferrer"
                    target="_blank"
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
      <Tabs onValueChange={handleTabChange} value={activeTab}>
        <TabsList className="mb-6">
          {tabs.map((tab) =>
            tab.id === 'settings' ? (
              <TooltipProvider delayDuration={200} key={tab.id}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <TabsTrigger
                      aria-label="Project Settings"
                      className="ml-auto"
                      value={tab.id}
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
                        onCommit={handleCommitTeamSlug}
                        options={teamOptions}
                        pending={pendingPath === '/team_slug'}
                        value={project.team.slug}
                      />
                    </div>

                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Slug</span>
                      <InlineText
                        onCommit={handleCommitSlug}
                        pending={pendingPath === '/slug'}
                        renderValue={renderSlugValue}
                        value={project.slug}
                      />
                    </div>

                    <div
                      className={`flex items-center justify-between border-b py-1.5 ${divider}`}
                    >
                      <span className={`text-sm ${label}`}>Project types</span>
                      <InlineMultiSelect
                        onCommit={handleCommitProjectTypeSlugs}
                        options={projectTypeOptions}
                        pending={pendingPath === '/project_type_slugs'}
                        values={(project.project_types || []).map(
                          (pt) => pt.slug,
                        )}
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
                      patch={patch}
                      pendingPath={pendingPath}
                      project={project}
                      projectSchema={projectSchema}
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Environments */}
              {sortedEnvironments.length > 0 && (
                <ProjectEnvironmentsCard
                  deploymentStatus={deploymentStatus}
                  environments={sortedEnvironments}
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
                        <div className="flex items-start gap-2.5" key={index}>
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
            project={project}
            projectId={project.id}
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
            initialAction={activeTab === 'notes' ? initialSubAction : undefined}
            initialNoteId={activeTab === 'notes' ? initialSubId : undefined}
            orgSlug={project.team.organization.slug}
            projectId={project.id}
            projectTypeSlugs={
              project.project_types && project.project_types.length > 0
                ? project.project_types.map((pt) => pt.slug)
                : project.project_type
                  ? [project.project_type.slug]
                  : []
            }
          />
        </TabsContent>
        <TabsContent value="operations-log">
          <OperationsLog
            embedded
            projectSlug={project.slug}
            showHeader={false}
            showSummary={false}
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
