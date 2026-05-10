import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Filter,
  Info,
  Settings2 as SettingsIcon,
  TrendingDown,
  XCircle,
} from 'lucide-react'

import {
  type AttributeContribution,
  getMyIdentities,
  getProjectBreakdown,
  getProjectSchema,
  getScoreTrend,
  listCurrentReleases,
  listIdentityPlugins,
  listLinkDefinitions,
  listProjectDocuments,
  listProjectPlugins,
  listProjectTypes,
  listScoringPolicies,
  listTeams,
  type ScoreTrend,
} from '@/api/endpoints'
import {
  type DeploymentRunStarted,
  DeployModal,
  PromoteModal,
} from '@/components/deploy/DeploymentModal'
import { DeploymentRunWatcher } from '@/components/deploy/DeploymentRunWatcher'
import { ProjectDocumentsTab } from '@/components/documents/ProjectDocumentsTab'
import { OperationsLog } from '@/components/OperationsLog'
import { ConfigurationTab } from '@/components/project/ConfigurationTab'
import { LogsTab } from '@/components/project/LogsTab'
import { ProjectActivityLog } from '@/components/ProjectActivityLog'
import { ProjectAttributesSection } from '@/components/ProjectAttributesSection'
import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ProjectRelationshipsTab } from '@/components/ProjectRelationshipsTab'
import { ProjectSettingsTab } from '@/components/ProjectSettingsTab'
import { ScoreHistoryTab } from '@/components/ScoreHistoryTab'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { LabelChip } from '@/components/ui/label-chip'
import { ScoreBadge } from '@/components/ui/score-badge'
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
import { formatFieldKey } from '@/lib/project-field-formatting'
import { sanitizeHttpUrl, sortEnvironments } from '@/lib/utils'
import type { Project, ScoringPolicy } from '@/types'

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
  'documents',
  'operations-log',
  'score-history',
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

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: currentReleases = [] } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, project.id, signal),
    queryKey: ['currentReleases', orgSlug, project.id],
  })

  const deploymentStatus: Record<
    string,
    {
      ciStatus: 'fail' | 'pass' | 'warn' | null
      runUrl: null | string
      status: string
      updated: string
      version: string
    }
  > = useMemo(() => {
    const out: Record<
      string,
      {
        ciStatus: 'fail' | 'pass' | 'warn' | null
        runUrl: null | string
        status: string
        updated: string
        version: string
      }
    > = {}
    for (const row of currentReleases) {
      if (!row.release || !row.last_event_at) continue
      // ``ci_status === 'unknown'`` is the API's null-equivalent;
      // collapse it so we don't render a useless gray dot.
      const ci =
        row.ci_status && row.ci_status !== 'unknown' ? row.ci_status : null
      out[row.environment.slug] = {
        ciStatus: ci,
        runUrl: row.external_run_url,
        status: row.current_status ?? '',
        updated: formatDistanceToNow(new Date(row.last_event_at), {
          addSuffix: true,
        }),
        version: row.release.version,
      }
    }
    return out
  }, [currentReleases])

  // Redirect to clean URL when the tab slug or sub-id is invalid.
  // ``deploy`` and ``promote`` are not page tabs — they are URL-driven
  // modal triggers (``/projects/<id>/deploy/<env>``) — so they bypass
  // the page-tab redirect, but they must carry a *known* env in
  // ``subId`` to be meaningful, ``promote`` requires a previous env in
  // the pipeline, *and* ``promote`` requires the upstream env to have a
  // deployed version (otherwise ``fromCommittish`` would be undefined
  // and the promote flow can't succeed).
  useEffect(() => {
    const isModalTab = initialTab === 'deploy' || initialTab === 'promote'
    if (initialTab && !VALID_TAB_SET.has(initialTab) && !isModalTab) {
      navigate(`/projects/${project.id}`, { replace: true })
      return
    }
    if (isModalTab) {
      if (!initialSubId) {
        navigate(`/projects/${project.id}`, { replace: true })
        return
      }
      // Wait for environments to load before validating; an empty list
      // here just means the project hasn't finished resolving.
      if (sortedEnvironments.length === 0) return
      const idx = sortedEnvironments.findIndex((e) => e.slug === initialSubId)
      if (idx < 0) {
        navigate(`/projects/${project.id}`, { replace: true })
        return
      }
      if (initialTab === 'promote') {
        if (idx <= 0) {
          navigate(`/projects/${project.id}`, { replace: true })
          return
        }
        const fromSlug = sortedEnvironments[idx - 1]?.slug
        const fromVersion = fromSlug
          ? deploymentStatus[fromSlug]?.version
          : undefined
        // Wait for the releases query (drives ``deploymentStatus``) to
        // settle before deciding the upstream is empty.
        if (currentReleases.length === 0) return
        if (!fromVersion) {
          navigate(`/projects/${project.id}`, { replace: true })
        }
      }
    }
  }, [
    currentReleases,
    deploymentStatus,
    initialSubId,
    initialTab,
    navigate,
    project.id,
    sortedEnvironments,
  ])

  const { data: linkDefs = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    queryKey: ['linkDefinitions', orgSlug],
  })

  const { data: scoreTrend } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => getScoreTrend(orgSlug, project.id, 30, signal),
    queryKey: ['scoreTrend', orgSlug, project.id],
    staleTime: 5 * 60 * 1000,
  })

  const { data: projectWithBreakdown } = useQuery({
    enabled: !!orgSlug && !!project.id && project.score != null,
    queryFn: ({ signal }) => getProjectBreakdown(orgSlug, project.id, signal),
    queryKey: ['projectBreakdown', orgSlug, project.id],
    staleTime: 5 * 60 * 1000,
  })
  const scoreBreakdown = projectWithBreakdown?.breakdown
  const [breakdownOpen, setBreakdownOpen] = useState(false)

  const { data: scoringPolicies = [] } = useQuery({
    enabled: breakdownOpen,
    queryFn: ({ signal }) => listScoringPolicies(signal),
    queryKey: ['scoringPolicies'],
    staleTime: 5 * 60 * 1000,
  })
  // Capture the score present at page load so intra-session changes are visible
  // even when the 30d baseline equals the current live score.
  const sessionBaseScore = useRef<null | number>(project.score ?? null)

  // Modal state is derived from the URL: ``/projects/<id>/deploy/<env>``
  // and ``/projects/<id>/promote/<env>``. Closing a modal navigates
  // back to ``/projects/<id>`` so the URL is the single source of truth
  // and a deploy/promote view is deep-linkable.
  const isDeployModal = initialTab === 'deploy' && !!initialSubId
  const isPromoteModal = initialTab === 'promote' && !!initialSubId
  const closeModal = useCallback(
    () => navigate(`/projects/${project.id}`, { replace: true }),
    [navigate, project.id],
  )
  const openDeploy = useCallback(
    (envSlug?: string) => {
      // The bare "Deploy" button doesn't carry an env, so default to
      // the entry-point env (idx 0) for first-time deployments.
      const slug = envSlug ?? sortedEnvironments[0]?.slug
      if (slug) navigate(`/projects/${project.id}/deploy/${slug}`)
    },
    [navigate, project.id, sortedEnvironments],
  )
  const openPromote = useCallback(
    (_fromEnvironment: string, toEnvironment: string) =>
      navigate(`/projects/${project.id}/promote/${toEnvironment}`),
    [navigate, project.id],
  )

  // Active deployment runs (one watcher per entry).  Pushed by the
  // DeployTab/PromoteTab onRunStarted callback; the watcher itself
  // calls back to remove its entry once the run reaches a terminal
  // state.  Refreshes the release-train view too so the freshly
  // recorded ``DeploymentEvent.status`` flips out of ``in_progress``.
  const [activeRuns, setActiveRuns] = useState<DeploymentRunStarted[]>([])
  const queryClient = useQueryClient()
  const handleRunStarted = useCallback((run: DeploymentRunStarted) => {
    setActiveRuns((prev) =>
      prev.some((r) => r.runId === run.runId) ? prev : [...prev, run],
    )
  }, [])
  const handleRunTerminal = useCallback(
    (runId: string) => {
      // Invalidate the originating project's release cache rather than
      // the currently-mounted project, so promotions trigger from one
      // project but settle while viewing another still refresh
      // correctly.
      setActiveRuns((prev) => {
        const settled = prev.find((r) => r.runId === runId)
        if (settled) {
          void queryClient.invalidateQueries({
            queryKey: [
              'currentReleases',
              settled.originOrgSlug,
              settled.originProjectId,
            ],
          })
        }
        return prev.filter((r) => r.runId !== runId)
      })
    },
    [queryClient],
  )

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
  const { data: projectDocuments = [] } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) =>
      listProjectDocuments(orgSlug, project.id, undefined, signal),
    queryKey: ['projectDocuments', orgSlug, project.id],
  })
  // Drives whether the Configuration / Logs tabs are surfaced. Only
  // treat the absence of a plugin as authoritative once the assignments
  // lookup has actually succeeded — a still-loading or errored query
  // must not render the tab as "no plugin", because that would silently
  // strip an existing tab and leave a deep-link landing on a blank
  // pane. While the query is unresolved or failed, we hold both flags
  // back; the redirect effect already waits on success before rerouting.
  const {
    data: projectPlugins,
    isFetched: projectPluginsFetched,
    isSuccess: projectPluginsSuccess,
  } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, project.id, signal),
    queryKey: ['project-plugins', orgSlug, project.id],
    staleTime: 5 * 60 * 1000,
  })
  const hasConfigurationPlugin =
    projectPluginsSuccess &&
    (projectPlugins ?? []).some((a) => a.tab === 'configuration')
  const hasLogsPlugin =
    projectPluginsSuccess &&
    (projectPlugins ?? []).some((a) => a.tab === 'logs')
  const deploymentPlugin = projectPluginsSuccess
    ? (projectPlugins ?? []).find((a) => a.tab === 'deployment')
    : undefined
  const deploymentIdentityPluginId =
    deploymentPlugin?.identity_plugin_id ?? null

  // Per-user identity connections — used to gate deploy/promote on the
  // current user actually having an active connection to the deployment
  // provider. Without this, chips render as buttons that 401 on click.
  // Fetch any time a deployment plugin exists so we can also surface the
  // identity-plugin label in the "connect to ..." banner even when the
  // assignment lacks an explicit identity_plugin_id.
  const {
    data: myIdentities,
    isError: myIdentitiesError,
    isLoading: myIdentitiesLoading,
    isSuccess: myIdentitiesSuccess,
  } = useQuery({
    enabled: !!deploymentPlugin,
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['my-identities'],
    staleTime: 5 * 60 * 1000,
  })
  // Look up the identity plugin's display label so the banner names the
  // provider the user actually has to authenticate against (e.g.
  // "GitHub Enterprise Cloud") rather than the deployment plugin label.
  // Fetch whenever a deployment plugin is present so the catalog is
  // available — we may need it even before ``deploymentIdentityPluginId``
  // resolves on the first render.
  const {
    data: identityPlugins,
    isError: identityPluginsError,
    isLoading: identityPluginsLoading,
  } = useQuery({
    enabled: !!orgSlug && !!deploymentPlugin,
    queryFn: ({ signal }) => listIdentityPlugins(orgSlug, signal),
    queryKey: ['identity-plugins', orgSlug],
    staleTime: 5 * 60 * 1000,
  })

  // Resolve the identity plugin we expect the user to authenticate
  // against. Prefer the explicit binding on the merged assignment; fall
  // back to a sibling identity plugin whose slug shares a prefix with
  // the deployment plugin's slug (e.g. ``github-enterprise-cloud`` ↔
  // ``github-deployment-ec``). The fallback covers the case where the
  // project-type assignment didn't bind an identity plugin but a
  // matching one exists in the org's plugin catalog.
  const resolvedIdentityPlugin = useMemo(() => {
    if (!deploymentPlugin) return null
    const catalog = identityPlugins ?? []
    if (deploymentIdentityPluginId) {
      const match = catalog.find(
        (p) => p.plugin_id === deploymentIdentityPluginId,
      )
      if (match) return match
    }
    if (catalog.length === 0) return null
    const dSlug = deploymentPlugin.plugin_slug
    const dHead = dSlug.split('-')[0] ?? ''
    return (
      catalog.find((p) => dSlug.startsWith(p.plugin_slug)) ??
      catalog.find((p) => p.plugin_slug.startsWith(dHead)) ??
      null
    )
  }, [deploymentPlugin, deploymentIdentityPluginId, identityPlugins])

  // A deployment plugin ALWAYS needs an identity connection — without an
  // active connection to the resolved identity plugin we keep the chips
  // non-interactive (the API would 401 anyway). Distinguish the three
  // not-ready states so the banner doesn't tell already-connected users
  // to "connect" while queries are still in flight or failing.
  const isUserConnectedToDeployment =
    !!resolvedIdentityPlugin &&
    myIdentitiesSuccess &&
    (myIdentities ?? []).some(
      (i) =>
        i.plugin_id === resolvedIdentityPlugin.plugin_id &&
        i.status === 'active',
    )
  const deploymentReadiness:
    | 'connected'
    | 'disconnected'
    | 'error'
    | 'loading' = !deploymentPlugin
    ? 'disconnected'
    : myIdentitiesLoading || identityPluginsLoading
      ? 'loading'
      : myIdentitiesError || identityPluginsError
        ? 'error'
        : isUserConnectedToDeployment
          ? 'connected'
          : 'disconnected'
  const canTriggerDeployments =
    !!deploymentPlugin && deploymentReadiness === 'connected'

  const deploymentConnectLabel = (() => {
    if (resolvedIdentityPlugin?.label) return resolvedIdentityPlugin.label
    if (deploymentIdentityPluginId) {
      const match = (myIdentities ?? []).find(
        (i) => i.plugin_id === deploymentIdentityPluginId,
      )
      if (match?.plugin_label) return match.plugin_label
    }
    if (deploymentPlugin?.label) return deploymentPlugin.label
    return 'the identity provider'
  })()

  // Redirect to overview when a deep-link points at a tab that no
  // longer surfaces (e.g. /configuration on a project type with no
  // configuration plugin assigned). Wait for the assignments query to
  // resolve successfully before deciding — otherwise the empty default
  // during the initial fetch redirects every direct navigation to
  // /logs or /configuration.
  useEffect(() => {
    if (!projectPluginsFetched || !projectPluginsSuccess) return
    if (
      (activeTab === 'configuration' && !hasConfigurationPlugin) ||
      (activeTab === 'logs' && !hasLogsPlugin)
    ) {
      navigate(`/projects/${project.id}`, { replace: true })
    }
  }, [
    activeTab,
    hasConfigurationPlugin,
    hasLogsPlugin,
    navigate,
    project.id,
    projectPluginsFetched,
    projectPluginsSuccess,
  ])

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
    ...(hasConfigurationPlugin
      ? [{ id: 'configuration' as const, label: 'Configuration' }]
      : []),
    { id: 'dependencies', label: 'Dependencies' },
    {
      id: 'documents',
      label:
        projectDocuments.length > 0
          ? `Documents (${projectDocuments.length})`
          : 'Documents',
    },
    ...(hasLogsPlugin ? [{ id: 'logs' as const, label: 'Logs' }] : []),
    { id: 'operations-log', label: 'Operations Log' },
    {
      id: 'relationships',
      label: (() => {
        const rel = project.relationships
        const total = (rel?.inbound_count ?? 0) + (rel?.outbound_count ?? 0)
        return `Relationships (${total})`
      })(),
    },
    { id: 'score-history', label: 'Score History' },
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

          {/* Deployment Pipeline — chips are the only entry points
               for Deploy/Promote, routed by position in the train. */}
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2">
              {sortedEnvironments.length > 0 &&
                sortedEnvironments.map((env, idx) => {
                  const deployment = deploymentStatus[env.slug]
                  const color = env.label_color
                  const ciDot = deployment
                    ? renderCiDot(deployment.ciStatus)
                    : null
                  // Release-train conventions, by position only — no
                  // hardcoded env names:
                  //   idx 0   — entry point, Deploy a chosen commit
                  //   idx 1   — Promote (tag + release the idx-0 build)
                  //   idx 2+  — Deploy: re-roll whatever was tagged at
                  //             idx 1 to a downstream env
                  const isPromoteSlot = idx === 1
                  const previousSlug = isPromoteSlot
                    ? sortedEnvironments[0]?.slug
                    : undefined
                  const handleClick = isPromoteSlot
                    ? () => openPromote(previousSlug as string, env.slug)
                    : () => openDeploy(env.slug)
                  const tooltipText = isPromoteSlot
                    ? 'Promote'
                    : 'Deploy / Redeploy'
                  const versionSuffix = deployment
                    ? `: ${deployment.version}`
                    : ''
                  const chipBody = color ? (
                    <LabelChip
                      className="rounded-md px-3 py-1.5 text-sm"
                      hex={color}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {env.name}
                        {versionSuffix}
                        {ciDot}
                      </span>
                    </LabelChip>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium">
                      {env.name}
                      {versionSuffix}
                      {ciDot}
                    </span>
                  )
                  return (
                    <span className="contents" key={env.slug}>
                      {idx > 0 && (
                        <ArrowRight className="h-4 w-4 text-tertiary" />
                      )}
                      {canTriggerDeployments ? (
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                aria-label={
                                  isPromoteSlot
                                    ? `Promote ${previousSlug} to ${env.name}`
                                    : `Deploy to ${env.name}`
                                }
                                className="cursor-pointer rounded-md transition hover:shadow-md hover:ring-1 hover:ring-ring hover:ring-offset-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                onClick={handleClick}
                                type="button"
                              >
                                {chipBody}
                              </button>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>{tooltipText}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        chipBody
                      )}
                    </span>
                  )
                })}
            </div>
            {deploymentPlugin && (
              <div className="flex items-center gap-1.5 text-xs italic text-tertiary">
                <Info className="h-3.5 w-3.5" />
                <span>
                  {deploymentReadiness === 'connected'
                    ? 'Click on an environment to deploy to it'
                    : deploymentReadiness === 'loading'
                      ? 'Checking deployment access…'
                      : deploymentReadiness === 'error'
                        ? 'Could not check deployment access — retry shortly'
                        : `Connect to ${deploymentConnectLabel} to enable deployments`}
                </span>
              </div>
            )}
          </div>
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
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[3fr_2fr] lg:items-start">
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

            {/* Right column: Health score + Activity */}
            <div className="flex flex-col gap-6">
              <Card>
                <CardHeader>
                  <CardTitle>Health &amp; compliance</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center gap-3">
                    <ScoreBadge
                      score={projectWithBreakdown?.score ?? project.score}
                      size="lg"
                      variant="square"
                    />
                    <div>
                      <p className={`text-xs ${muted}`}>Health score</p>
                      <ScoreTrendPill
                        liveScore={projectWithBreakdown?.score ?? project.score}
                        scoreTrend={scoreTrend}
                        sessionBaseScore={sessionBaseScore}
                      />
                    </div>
                  </div>
                </CardContent>
                {scoreBreakdown &&
                  scoreBreakdown.attribute_contributions.length > 0 && (
                    <CardFooter className="flex-col items-start gap-0 border-t border-tertiary p-0">
                      <button
                        className="flex w-full items-center justify-between px-6 py-3 text-xs font-medium text-tertiary hover:text-primary"
                        onClick={() => setBreakdownOpen((o) => !o)}
                        type="button"
                      >
                        Score breakdown
                        <ChevronDown
                          className={`h-3.5 w-3.5 transition-transform ${breakdownOpen ? 'rotate-180' : ''}`}
                        />
                      </button>
                      {breakdownOpen && (
                        <ScoreBreakdownDetail
                          contributions={scoreBreakdown.attribute_contributions}
                          policies={scoringPolicies}
                        />
                      )}
                    </CardFooter>
                  )}
              </Card>

              <Card className="flex flex-col" style={{ maxHeight: '600px' }}>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>Recent activity</CardTitle>
                  <button className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs text-secondary transition-colors hover:bg-secondary hover:text-primary">
                    <Filter className="h-3 w-3" />
                    Filter
                  </button>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
                  <ProjectActivityLog
                    orgSlug={project.team.organization.slug}
                    projectId={project.id}
                    projectSlug={project.slug}
                  />
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {hasConfigurationPlugin && (
          <TabsContent value="configuration">
            <ConfigurationTab
              environments={sortedEnvironments}
              orgSlug={orgSlug}
              projectId={project.id}
              projectSlug={project.slug}
              teamSlug={project.team.slug}
            />
          </TabsContent>
        )}
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
        {hasLogsPlugin && (
          <TabsContent value="logs">
            <LogsTab
              environments={sortedEnvironments}
              orgSlug={orgSlug}
              projectId={project.id}
            />
          </TabsContent>
        )}
        <TabsContent value="documents">
          <ProjectDocumentsTab
            initialAction={
              activeTab === 'documents' ? initialSubAction : undefined
            }
            initialDocumentId={
              activeTab === 'documents' ? initialSubId : undefined
            }
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
        <TabsContent value="score-history">
          <ScoreHistoryTab orgSlug={orgSlug} projectId={project.id} />
        </TabsContent>
        <TabsContent value="settings">
          <ProjectSettingsTab project={project} />
        </TabsContent>
      </Tabs>
      <DeployModal
        environments={sortedEnvironments}
        initialEnvSlug={isDeployModal ? initialSubId : undefined}
        onOpenChange={(open) => {
          if (!open) closeModal()
        }}
        onRunStarted={handleRunStarted}
        open={isDeployModal}
        orgSlug={orgSlug}
        projectId={project.id}
        projectName={project.name}
      />
      {(() => {
        if (!isPromoteModal) return null
        const toIdx = sortedEnvironments.findIndex(
          (e) => e.slug === initialSubId,
        )
        // Promote requires a previous env in the pipeline to act as the
        // source AND a deployed version on that upstream env (else
        // ``fromCommittish`` would be undefined and the API can't
        // resolve the source). ``idx <= 0`` means the URL points at the
        // entry-point env (or an unknown one); the redirect effect
        // above will already navigate away — render nothing here so we
        // never mount PromoteModal in an impossible state.
        if (toIdx <= 0) return null
        const fromSlug = sortedEnvironments[toIdx - 1]?.slug
        const fromVersion = fromSlug
          ? deploymentStatus[fromSlug]?.version
          : undefined
        if (!fromSlug || !fromVersion) return null
        return (
          <PromoteModal
            environments={sortedEnvironments}
            fromCommittish={fromVersion}
            fromEnvironment={fromSlug}
            onOpenChange={(open) => {
              if (!open) closeModal()
            }}
            onRunStarted={handleRunStarted}
            open={isPromoteModal}
            orgSlug={orgSlug}
            projectId={project.id}
            projectName={project.name}
            toEnvironment={initialSubId as string}
          />
        )
      })()}
      {activeRuns.map((run) => (
        // Bind each watcher to the org/project that triggered the run
        // so polling stays correct if the user navigates to another
        // project before the workflow settles.
        <DeploymentRunWatcher
          actionLabel={run.actionLabel}
          actionUrl={run.actionUrl}
          envName={run.envName}
          initialStatus={run.initialStatus}
          key={run.runId}
          onTerminal={handleRunTerminal}
          orgSlug={run.originOrgSlug}
          projectId={run.originProjectId}
          runId={run.runId}
          runUrl={run.runUrl}
          toastId={run.toastId}
        />
      ))}
    </div>
  )
}

function buildRecommendation(
  c: AttributeContribution,
  policy: ScoringPolicy,
): null | string {
  const current = c.mapped_score
  if (policy.value_score_map) {
    const better = Object.entries(policy.value_score_map)
      .filter(([, score]) => score > current)
      .sort(([, a], [, b]) => b - a)
    if (better.length === 0) return null
    const topScore = better[0][1]
    const top = better
      .filter(([, score]) => score === topScore)
      .map(([name]) => name)
    if (top.length === 1) return `Update to ${top[0]}`
    if (top.length === 2) return `Update to ${top[0]} or ${top[1]}`
    return `Update to ${top.slice(0, -1).join(', ')}, or ${top[top.length - 1]}`
  }
  if (policy.range_score_map) {
    const better = Object.entries(policy.range_score_map)
      .filter(([, score]) => score > current)
      .sort(([, a], [, b]) => b - a)
    if (better.length === 0) return null
    const [target] = better[0]
    return `Update to reach ${target}`
  }
  return null
}

function fmtAttributeValue(value: unknown): string {
  const n = Number(value)
  return isFinite(n) && String(value).trim() !== ''
    ? String(Math.round(n))
    : String(value)
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

function renderCiDot(status: 'fail' | 'pass' | 'warn' | null): React.ReactNode {
  if (status === 'pass')
    return <CheckCircle2 aria-label="CI passing" className="h-3.5 w-3.5" />
  if (status === 'fail')
    return <XCircle aria-label="CI failing" className="h-3.5 w-3.5" />
  if (status === 'warn')
    return <AlertCircle aria-label="CI warning" className="h-3.5 w-3.5" />
  return null
}

function ScoreBreakdownDetail({
  contributions,
  policies,
}: {
  contributions: AttributeContribution[]
  policies: ScoringPolicy[]
}) {
  const totalWeight = contributions.reduce((s, c) => s + c.weight, 0)
  const policyBySlug = useMemo(() => {
    const map = new Map<string, ScoringPolicy>()
    for (const p of policies) map.set(p.slug, p)
    return map
  }, [policies])

  const enriched = contributions.map((c) => {
    const maxPts = totalWeight > 0 ? (c.weight / totalWeight) * 100 : 0
    return {
      contribution: c,
      isPerfect: c.mapped_score >= 100,
      maxPts,
      policy: policyBySlug.get(c.policy_slug),
    }
  })
  const improve = enriched
    .filter((e) => !e.isPerfect)
    .sort(
      (a, b) =>
        b.maxPts -
        b.contribution.weighted_contribution -
        (a.maxPts - a.contribution.weighted_contribution),
    )
  const perfect = enriched
    .filter((e) => e.isPerfect)
    .sort((a, b) => b.maxPts - a.maxPts)

  return (
    <div className="flex w-full flex-col gap-5 px-6 pb-4">
      <p className="text-[11px] text-tertiary">
        {contributions.length} policies
      </p>
      {improve.length > 0 && (
        <section>
          <div className="mb-2.5 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            <span>To improve</span>
            <span className="font-mono">{improve.length}</span>
          </div>
          <div className="flex flex-col gap-3">
            {improve.map(({ contribution: c, maxPts, policy }) => {
              const fillPct =
                maxPts > 0 ? (c.weighted_contribution / maxPts) * 100 : 0
              const lost = Math.round(maxPts - c.weighted_contribution)
              const policyName = formatFieldKey(
                c.policy_slug.replace(/-/g, '_'),
              )
              const recommendation = policy
                ? buildRecommendation(c, policy)
                : null
              return (
                <div
                  className="rounded-md border border-tertiary bg-primary p-3.5"
                  key={c.policy_slug}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex min-w-0 items-baseline gap-1.5">
                      <span className="text-[14px] font-semibold text-primary">
                        {policyName}
                      </span>
                      <span className="font-mono text-[11px] text-tertiary">
                        w{c.weight}
                      </span>
                    </div>
                    <div className="shrink-0 font-mono text-[13px] tabular-nums">
                      <span className="font-semibold text-primary">
                        {Math.round(c.weighted_contribution)}
                      </span>
                      <span className="text-tertiary">
                        {' '}
                        / {Math.round(maxPts)}
                      </span>
                    </div>
                  </div>
                  <p className="mb-2.5 mt-1 text-[13px] text-secondary">
                    Currently{' '}
                    <span className="font-medium text-amber-text">
                      {c.value != null ? fmtAttributeValue(c.value) : 'Not set'}
                    </span>
                  </p>
                  <div className="relative h-1.5 rounded-full bg-secondary">
                    {fillPct > 0 && (
                      <div
                        className="absolute inset-y-0 left-0 rounded-full bg-action"
                        style={{ width: `${fillPct}%` }}
                      />
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-1.5 text-[12.5px] text-secondary">
                    <TrendingDown className="h-3 w-3 shrink-0 text-tertiary" />
                    <span>
                      Losing{' '}
                      <span className="font-mono font-medium text-danger">
                        {lost} pts
                      </span>
                      {recommendation ? ` · ${recommendation}` : ''}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}
      {perfect.length > 0 && (
        <section>
          <div className="mb-2.5 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-tertiary">
            <span>At maximum</span>
            <span className="font-mono">{perfect.length}</span>
          </div>
          <div className="overflow-hidden rounded-md border border-tertiary">
            {perfect.map(({ contribution: c, maxPts }, idx) => {
              const policyName = formatFieldKey(
                c.policy_slug.replace(/-/g, '_'),
              )
              return (
                <div
                  className={`grid grid-cols-[auto_1fr_auto] items-center gap-2.5 bg-primary px-3 py-2.5 ${
                    idx > 0 ? 'border-t border-tertiary' : ''
                  }`}
                  key={c.policy_slug}
                >
                  <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-success text-success">
                    <Check className="h-2.5 w-2.5" strokeWidth={3} />
                  </span>
                  <span className="text-[13.5px] font-medium text-primary">
                    {policyName}
                    <span className="ml-1.5 font-normal text-tertiary">
                      {c.value != null ? fmtAttributeValue(c.value) : 'Not set'}
                    </span>
                  </span>
                  <span className="font-mono text-[12px] tabular-nums text-tertiary">
                    {Math.round(c.weighted_contribution)}/{Math.round(maxPts)}
                  </span>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

function ScoreTrendPill({
  liveScore,
  scoreTrend,
  sessionBaseScore,
}: {
  liveScore: null | number | undefined
  scoreTrend: ScoreTrend | undefined
  sessionBaseScore: React.RefObject<null | number>
}) {
  if (liveScore == null) return null

  const sessionDelta =
    sessionBaseScore.current != null
      ? Math.round((liveScore - sessionBaseScore.current) * 100) / 100
      : null
  const showSession = sessionDelta != null && sessionDelta !== 0

  let delta: null | number
  let trendLabel: string
  if (showSession) {
    delta = sessionDelta
    trendLabel = 'session'
  } else if (scoreTrend?.previous != null) {
    delta = Math.round((liveScore - scoreTrend.previous) * 100) / 100
    trendLabel = `${scoreTrend.period_days}d`
  } else {
    return null
  }

  return (
    <p className="font-mono text-xs text-tertiary">
      {delta > 0 ? '+' : ''}
      {Math.round(delta)} pts / {trendLabel}
    </p>
  )
}
