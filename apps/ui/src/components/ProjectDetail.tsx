import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  Check,
  ChevronDown,
  Copy,
  Stethoscope as DoctorIcon,
  Filter,
  RefreshCw,
  Settings2 as SettingsIcon,
  TrendingDown,
} from 'lucide-react'

import {
  type AnalysisResultStatus,
  type AttributeContribution,
  getMyIdentities,
  getProjectAnalysis,
  getProjectBreakdown,
  getProjectPullRequests,
  getProjectSchema,
  getScoreTrend,
  listCurrentReleases,
  listIdentityPlugins,
  listIntegrations,
  listLinkDefinitions,
  listProjectDocuments,
  listProjectPlugins,
  listScoringPolicies,
  previewProjectLifecycle,
  type ProjectSchemaResponse,
  type ScoreTrend,
} from '@/api/endpoints'
import { DependenciesTab } from '@/components/dependencies/DependenciesTab'
import { ConnectIdentityPrompt } from '@/components/deploy/ConnectIdentityPrompt'
import {
  type DeploymentRunStarted,
  ReleaseModal,
} from '@/components/deploy/DeploymentModal'
import { DeploymentRunWatcher } from '@/components/deploy/DeploymentRunWatcher'
import { DeploymentsTab } from '@/components/deployments/DeploymentsTab'
import { ProjectDocumentsTab } from '@/components/documents/ProjectDocumentsTab'
import { OperationsLog } from '@/components/OperationsLog'
import { ConfigurationTab } from '@/components/project/ConfigurationTab'
import { IncidentsTab } from '@/components/project/IncidentsTab'
import { LogsTab } from '@/components/project/LogsTab'
import { ProjectPullRequestsTab } from '@/components/project/ProjectPullRequestsTab'
import { ProjectActivityLog } from '@/components/ProjectActivityLog'
import { ProjectAttributesSection } from '@/components/ProjectAttributesSection'
import { ProjectDoctorTab } from '@/components/ProjectDoctorTab'
import { ProjectEnvironmentsCard } from '@/components/ProjectEnvironmentsCard'
import { ProjectRelationshipsTab } from '@/components/ProjectRelationshipsTab'
import { ProjectSettingsTab } from '@/components/ProjectSettingsTab'
import { ReleasesTab } from '@/components/releases/ReleasesTab'
import { RelocatePreviewDialog } from '@/components/RelocatePreviewDialog'
import { ScoreHistoryTab } from '@/components/ScoreHistoryTab'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { InlineMultiSelect } from '@/components/ui/inline-edit/InlineMultiSelect'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineTextarea } from '@/components/ui/inline-edit/InlineTextarea'
import { ScoreBadge } from '@/components/ui/score-badge'
import { Sk, SkText, Swap } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  IconTooltip,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useBalancedEnvLayout } from '@/hooks/useBalancedEnvLayout'
import { useClipboard } from '@/hooks/useClipboard'
import { useProjectTypes, useTeams } from '@/hooks/useOrgResources'
import { useProjectPatch } from '@/hooks/useProjectPatch'
import { formatDateTime } from '@/lib/formatDate'
import { getIcon, useIconRegistryVersion } from '@/lib/icons'
import { formatFieldKey } from '@/lib/project-field-formatting'
import { treatNotFoundAsNull } from '@/lib/queryHelpers'
import { sanitizeHttpUrl, sortEnvironments } from '@/lib/utils'
import type { LifecyclePreviewEntry, Project, ScoringPolicy } from '@/types'

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
  'deployments',
  'relationships',
  'releases',
  'logs',
  'incidents',
  'documents',
  'operations-log',
  'pull-requests',
  'score-history',
  'doctor',
  'settings',
] as const

type TabType = (typeof VALID_TABS)[number]

const VALID_TAB_SET: Set<string> = new Set(VALID_TABS)

// fallow-ignore-next-line complexity
export function ProjectDetail({
  initialSubAction,
  initialSubId,
  initialTab,
  project,
}: ProjectDetailProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const { patch, pendingPath } = useProjectPatch(orgSlug, project.id)
  // When a project-type change would relocate a backing remote, hold the
  // pending slugs + the relocating plugins here to drive the opt-in
  // confirmation dialog (null = no pending relocate decision).
  const [relocatePreview, setRelocatePreview] = useState<null | {
    entries: LifecyclePreviewEntry[]
    slugs: string[]
  }>(null)
  // Tracks the in-flight lifecycle-preview request so a later commit can
  // cancel an earlier one and we can ignore superseded responses (which
  // would otherwise reopen the dialog with stale slugs).
  const previewRequestRef = useRef<AbortController | null>(null)
  const navigate = useNavigate()
  const { copied: copiedProjectId, copy: copyProjectId } = useClipboard()

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

  // Decides whether the Environments card nests under Project details or spans
  // the full width below both overview columns (see hook for the rule).
  const {
    activityHeaderRef,
    activityInnerRef,
    activityMaxHeightPx,
    detailsRef,
    healthRef,
    spanFull: envSpanFull,
  } = useBalancedEnvLayout()

  const { data: currentReleases = [], isPending: releasesPending } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, project.id, signal),
    queryKey: ['currentReleases', orgSlug, project.id],
  })

  const deploymentStatus: Record<
    string,
    {
      ciStatus: 'fail' | 'pass' | 'warn' | null
      committish: string
      notes: null | string
      performedBy: null | string
      performedByEmail: null | string
      runUrl: null | string
      status: string
      tag: null | string
      updated: string
    }
    // fallow-ignore-next-line complexity
  > = useMemo(() => {
    const out: Record<
      string,
      {
        ciStatus: 'fail' | 'pass' | 'warn' | null
        committish: string
        notes: null | string
        performedBy: null | string
        performedByEmail: null | string
        runUrl: null | string
        status: string
        tag: null | string
        updated: string
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
        committish: row.release.committish,
        notes: row.release.description ?? null,
        performedBy: row.performed_by ?? null,
        performedByEmail: row.performed_by_email ?? null,
        runUrl: row.external_run_url,
        status: row.current_status ?? '',
        tag: row.release.tag ?? null,
        updated: formatDistanceToNow(new Date(row.last_event_at), {
          addSuffix: true,
        }),
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
  // fallow-ignore-next-line complexity
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
        const targetEnv = sortedEnvironments[idx]
        if (idx <= 0 || !(targetEnv?.can_promote ?? false)) {
          navigate(`/projects/${project.id}`, { replace: true })
          return
        }
        const fromSlug = sortedEnvironments[idx - 1]?.slug
        const fromCommittish = fromSlug
          ? deploymentStatus[fromSlug]?.committish
          : undefined
        // Wait for the releases query (drives ``deploymentStatus``) to
        // settle before deciding the upstream is empty. Use the
        // query's pending flag, not array length — a project with
        // genuinely zero releases would otherwise stay stuck here
        // without redirecting.
        if (releasesPending) return
        if (!fromCommittish) {
          navigate(`/projects/${project.id}`, { replace: true })
        }
      }
    }
  }, [
    deploymentStatus,
    initialSubId,
    initialTab,
    navigate,
    project.id,
    releasesPending,
    sortedEnvironments,
  ])

  const { data: linkDefs = [], isPending: linkDefsPending } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    queryKey: ['linkDefinitions', orgSlug],
  })

  // Org integrations supply the name/icon for integration dashboard links in
  // the header bar; shares IntegrationsCard's cache key.
  const { data: orgIntegrations = [], isPending: orgIntegrationsPending } =
    useQuery({
      enabled: !!orgSlug,
      queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
      queryKey: ['integrations', orgSlug],
      staleTime: 60 * 1000,
    })

  // Overview-tab-only queries: skip when the user lands on a deeper tab
  // (e.g. /projects/:id/logs via deep link) — the overview cards that
  // consume these aren't mounted in that case.
  const { data: scoreTrend, isPending: scoreTrendPending } = useQuery({
    enabled: !!orgSlug && !!project.id && activeTab === 'overview',
    queryFn: ({ signal }) => getScoreTrend(orgSlug, project.id, 30, signal),
    queryKey: ['scoreTrend', orgSlug, project.id],
    staleTime: 5 * 60 * 1000,
  })

  const { data: projectWithBreakdown } = useQuery({
    enabled:
      !!orgSlug &&
      !!project.id &&
      project.score != null &&
      activeTab === 'overview',
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

  // Drives the Doctor tab icon color. A 404 from the API means no
  // report has been generated yet — render that as null instead of
  // throwing.
  const { data: doctorReport } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) =>
      treatNotFoundAsNull(() =>
        getProjectAnalysis(orgSlug, project.id, signal),
      ),
    queryKey: ['projectAnalysis', orgSlug, project.id],
    staleTime: 60 * 1000,
  })
  const doctorOverallStatus: AnalysisResultStatus | null =
    doctorReport?.overall_status ?? null
  const doctorIconClass =
    doctorOverallStatus === 'fail'
      ? 'text-danger'
      : doctorOverallStatus === 'warn'
        ? 'text-warning'
        : doctorOverallStatus === 'pass'
          ? 'text-success'
          : 'text-tertiary'
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
  const [isRefreshing, setIsRefreshing] = useState(false)
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    try {
      // Reload everything scoped to this project (detail, releases,
      // events, score trends/breakdown, plugins, schema, …) — every
      // query whose key carries this project id. Org-level lookups
      // (link defs, scoring policies, identity plugins) are left alone.
      await queryClient.invalidateQueries({
        predicate: (q) => q.queryKey.includes(project.id),
      })
    } finally {
      setIsRefreshing(false)
    }
  }, [queryClient, project.id])
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

  // Overview-only: feeds ProjectAttributesSection inside <TabsContent
  // value="overview">. The other tabs render their own components.
  const { data: projectSchema, isPending: projectSchemaPending } = useQuery({
    enabled: !!orgSlug && !!project.id && activeTab === 'overview',
    queryFn: ({ signal }) => getProjectSchema(orgSlug, project.id, signal),
    queryKey: ['projectSchema', orgSlug, project.id],
  })

  const { data: teams = [] } = useTeams(orgSlug)
  const { data: projectTypes = [] } = useProjectTypes(orgSlug)
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
  // `select` derives the tab-presence flags + deployment plugin once per
  // payload change, instead of recomputing them on every render (the
  // previous code walked `projectPlugins` four times per render via
  // .some/.find).
  const {
    data: projectPluginsView,
    isFetched: projectPluginsFetched,
    isSuccess: projectPluginsSuccess,
  } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, project.id, signal),
    queryKey: ['project-plugins', orgSlug, project.id],
    select: (plugins) => ({
      deploymentPlugin: plugins.find((a) => a.plugin_type === 'deployment'),
      hasConfigurationPlugin: plugins.some(
        (a) => a.plugin_type === 'configuration',
      ),
      hasIncidentsPlugin: plugins.some((a) => a.plugin_type === 'incidents'),
      hasLifecyclePlugin: plugins.some((a) => a.plugin_type === 'lifecycle'),
      hasLogsPlugin: plugins.some((a) => a.plugin_type === 'logs'),
    }),
    staleTime: 5 * 60 * 1000,
  })
  const hasConfigurationPlugin =
    projectPluginsSuccess &&
    (projectPluginsView?.hasConfigurationPlugin ?? false)
  const hasLogsPlugin =
    projectPluginsSuccess && (projectPluginsView?.hasLogsPlugin ?? false)
  const hasIncidentsPlugin =
    projectPluginsSuccess && (projectPluginsView?.hasIncidentsPlugin ?? false)
  const hasLifecyclePlugin =
    projectPluginsSuccess && (projectPluginsView?.hasLifecyclePlugin ?? false)
  const deploymentPlugin = projectPluginsSuccess
    ? projectPluginsView?.deploymentPlugin
    : undefined
  const deploymentIdentityPluginId =
    deploymentPlugin?.identity_plugin_id ?? null

  // Build-and-release-only projects: a deployment plugin is assigned and the
  // project's type is marked ``releasable`` (library / image — published via
  // tag + GitHub release with no deploy step), so the "Releases" tab shows.
  // ``releasable`` and ``deployable`` are mutually exclusive on the project
  // type; the future Deployments tab gates on the latter (see isDeployable).
  const isReleasable = (project.project_types ?? []).some(
    (pt) => (pt as { releasable?: boolean }).releasable === true,
  )
  const isReleaseOnly = !!deploymentPlugin && isReleasable

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
  // fallow-ignore-next-line complexity
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
        i.plugin === resolvedIdentityPlugin.plugin_slug &&
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
  const isDeployable = (project.project_types ?? []).some(
    (pt) => (pt as { deployable?: boolean }).deployable === true,
  )
  const canTriggerDeployments =
    isDeployable && !!deploymentPlugin && deploymentReadiness === 'connected'
  // Deployable projects with a pipeline get the Deployments tab — the
  // counterpart of the release-only "Releases" tab above.
  const hasDeploymentsTab =
    isDeployable && !!deploymentPlugin && sortedEnvironments.length > 0

  // fallow-ignore-next-line complexity
  const deploymentConnectLabel = (() => {
    if (resolvedIdentityPlugin?.label) return resolvedIdentityPlugin.label
    if (deploymentIdentityPluginId) {
      const match = (identityPlugins ?? []).find(
        (p) => p.plugin_id === deploymentIdentityPluginId,
      )
      if (match?.label) return match.label
    }
    if (deploymentPlugin?.label) return deploymentPlugin.label
    return 'the identity provider'
  })()

  const { data: openPrCountData } = useQuery({
    enabled: hasLifecyclePlugin && !!orgSlug && !!project.id,
    queryFn: ({ signal }) =>
      getProjectPullRequests(
        orgSlug,
        project.id,
        { limit: 1, state: 'open' },
        signal,
      ),
    queryKey: ['project-prs-count', orgSlug, project.id],
    staleTime: 60_000,
  })
  const openPrCount = openPrCountData?.total ?? 0

  // Redirect to overview when a deep-link points at a tab that no
  // longer surfaces (e.g. /configuration on a project type with no
  // configuration plugin assigned). Wait for the assignments query to
  // resolve successfully before deciding — otherwise the empty default
  // during the initial fetch redirects every direct navigation to
  // /logs or /configuration.
  // fallow-ignore-next-line complexity
  useEffect(() => {
    if (!projectPluginsFetched || !projectPluginsSuccess) return
    if (
      (activeTab === 'configuration' && !hasConfigurationPlugin) ||
      (activeTab === 'logs' && !hasLogsPlugin) ||
      (activeTab === 'incidents' && !hasIncidentsPlugin) ||
      (activeTab === 'releases' && !isReleaseOnly) ||
      (activeTab === 'deployments' && !hasDeploymentsTab) ||
      (activeTab === 'pull-requests' && !hasLifecyclePlugin)
    ) {
      navigate(`/projects/${project.id}`, { replace: true })
    }
  }, [
    activeTab,
    hasConfigurationPlugin,
    hasDeploymentsTab,
    hasIncidentsPlugin,
    hasLifecyclePlugin,
    hasLogsPlugin,
    isReleaseOnly,
    navigate,
    project.id,
    projectPluginsFetched,
    projectPluginsSuccess,
  ])

  // Bumps when an icon-set chunk finishes loading; include in useMemo deps
  // where icons are resolved so they refresh once available.
  const iconRegistryVersion = useIconRegistryVersion()

  // Environments card resolves once its deployment-status (currentReleases)
  // and schema-driven edge attributes (projectSchema) land; the env list
  // itself is already on `project`.
  const envCardReady = !releasesPending && !projectSchemaPending

  const linkDefMap = useMemo(
    () => Object.fromEntries(linkDefs.map((ld) => [ld.slug, ld])),
    [linkDefs],
  )

  const integrationMap = useMemo(
    () => Object.fromEntries(orgIntegrations.map((i) => [i.slug, i])),
    [orgIntegrations],
  )

  // The header bar merges two sources, sorted together alphabetically:
  //   1. project.links entries that resolve to an org link definition
  //      (name/icon from the definition). Keys without a definition are
  //      skipped — integration dashboard links live in links keyed by
  //      integration slug and are rendered from `services` below, and any
  //      other undefined key is an orphaned link we no longer surface.
  //   2. live integration dashboard links from project.services (edges only,
  //      so orphaned link entries never appear), name/icon from the
  //      integration.
  const externalLinks = useMemo(() => {
    const defLinks = Object.entries(project.links || {})
      .map(([key, url]) => {
        const def = linkDefMap[key]
        if (!def) return null
        const safeUrl = sanitizeHttpUrl(url)
        if (!safeUrl) return null
        return {
          Icon: getIcon(def.icon),
          key,
          label: def.name || key.replace(/_/g, ' '),
          url: safeUrl,
        }
      })
      .filter((link): link is NonNullable<typeof link> => link !== null)

    const serviceLinks = (project.services || [])
      .map((svc) => {
        const safeUrl = svc.dashboard_url
          ? sanitizeHttpUrl(svc.dashboard_url)
          : null
        if (!safeUrl) return null
        const integration = integrationMap[svc.integration_slug]
        return {
          Icon: getIcon(integration?.icon),
          key: `service:${svc.integration_slug}`,
          label: integrationLinkLabel(integration, svc),
          url: safeUrl,
        }
      })
      .filter((link): link is NonNullable<typeof link> => link !== null)

    return [...defLinks, ...serviceLinks].sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    project.links,
    project.services,
    linkDefMap,
    integrationMap,
    iconRegistryVersion,
  ])

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
    async (v: string[]) => {
      // No lifecycle plugin assigned → no remote can relocate; commit
      // directly and skip the preview round-trip.
      if (!hasLifecyclePlugin) {
        await patch('/project_type_slugs', v)
        return
      }
      const relocating = await previewRelocations(
        previewRequestRef,
        orgSlug,
        project.id,
        v,
      )
      // Superseded by a newer commit → that call owns the outcome; bail.
      if (relocating === null) return
      // Nothing would move → plain metadata change, no confirmation needed.
      if (relocating.length === 0) {
        await patch('/project_type_slugs', v)
        return
      }
      setRelocatePreview({ entries: relocating, slugs: v })
    },
    [hasLifecyclePlugin, orgSlug, project.id, patch],
  )
  const handleRelocateConfirm = useCallback(
    async (transfer: boolean) => {
      const decision = relocatePreview
      if (!decision) return
      // Keep the dialog mounted during the patch so it can render its
      // pending state, and so a failure preserves the user's preview and
      // transfer choice instead of silently dropping them.
      await patch('/project_type_slugs', decision.slugs, {
        transferRepository: transfer,
      })
      setRelocatePreview(null)
    },
    [relocatePreview, patch],
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
    ...(hasDeploymentsTab
      ? [{ id: 'deployments' as const, label: 'Deployments' }]
      : []),
    {
      id: 'documents',
      label:
        projectDocuments.length > 0
          ? `Documents (${projectDocuments.length})`
          : 'Documents',
    },
    ...(hasIncidentsPlugin
      ? [{ id: 'incidents' as const, label: 'Incidents' }]
      : []),
    ...(hasLogsPlugin ? [{ id: 'logs' as const, label: 'Logs' }] : []),
    { id: 'operations-log', label: 'Operations Log' },
    ...(isReleaseOnly ? [{ id: 'releases' as const, label: 'Releases' }] : []),
    ...(hasLifecyclePlugin
      ? [
          {
            id: 'pull-requests' as const,
            label:
              openPrCount > 0
                ? `Pull Requests (${openPrCount})`
                : 'Pull Requests',
          },
        ]
      : []),
    {
      id: 'relationships',
      // fallow-ignore-next-line complexity
      label: (() => {
        const rel = project.relationships
        const total = (rel?.inbound_count ?? 0) + (rel?.outbound_count ?? 0)
        return `Relationships (${total})`
      })(),
    },
    { id: 'score-history', label: 'Score History' },
    { id: 'doctor', label: '' },
    { id: 'settings', label: '' },
  ]

  return (
    <div className="max-w-project-detail mx-auto px-6 py-8">
      {/* Project Header */}
      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="mb-1 ml-[-18px] flex items-center gap-3">
              <InlineText
                className="text-[1.75rem]"
                onCommit={handleCommitName}
                pending={pendingPath === '/name'}
                renderValue={renderNameValue}
                value={project.name}
              />
              <IconTooltip label="Copy project ID">
                <Button
                  aria-label="Copy project ID"
                  onClick={() => void copyProjectId(project.id)}
                  size="sm"
                  variant="ghost"
                >
                  {copiedProjectId ? (
                    <Check className="size-4 text-green-500" />
                  ) : (
                    <Copy className="text-secondary size-4" />
                  )}
                </Button>
              </IconTooltip>
              {project.archived && (
                <span className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium tracking-wide text-amber-800 uppercase dark:bg-amber-950 dark:text-amber-200">
                  Archived
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="text-secondary mt-3 ml-[-18px]">
          <InlineTextarea
            onCommit={handleCommitDescription}
            pending={pendingPath === '/description'}
            placeholder="Add a description…"
            rows={2}
            value={project.description ?? null}
          />
        </div>

        {/* External Links — reveal once link definitions land so labels and
            icons resolve, rather than flashing raw keys first. */}
        {externalLinks.length > 0 && (
          <Swap
            className="mt-3"
            ready={!linkDefsPending && !orgIntegrationsPending}
            skeleton={<LinksSkeleton count={externalLinks.length} />}
          >
            <div className="flex flex-wrap items-center gap-3">
              {externalLinks.map(
                ({ Icon, key, label: linkLabel, url }, index) => (
                  <span className="flex items-center gap-1.5" key={key}>
                    {index > 0 && (
                      <span className="text-tertiary mr-1.5">|</span>
                    )}
                    <a
                      className={
                        'text-warning flex items-center gap-1.5 text-sm hover:underline'
                      }
                      href={url}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      <Icon className="size-4" />
                      <span>{linkLabel}</span>
                    </a>
                  </span>
                ),
              )}
            </div>
          </Swap>
        )}
      </div>

      {/* Tabs */}
      <Tabs onValueChange={handleTabChange} value={activeTab}>
        <TabsList className="mb-6">
          {tabs.map((tab) => {
            if (tab.id === 'doctor') {
              return (
                <TooltipProvider delayDuration={200} key={tab.id}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <TabsTrigger
                        aria-label="Project Doctor"
                        className="ml-auto"
                        value={tab.id}
                      >
                        <DoctorIcon className={`size-4 ${doctorIconClass}`} />
                      </TabsTrigger>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Project Doctor</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )
            }
            if (tab.id === 'settings') {
              return (
                <Fragment key={tab.id}>
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          aria-label="Refresh project data"
                          className="text-muted-foreground hover:text-primary -mb-px inline-flex items-center justify-center border-b-2 border-transparent px-1 pt-1 pb-2 transition-colors disabled:opacity-50"
                          disabled={isRefreshing}
                          onClick={() => void handleRefresh()}
                          type="button"
                        >
                          <RefreshCw
                            className={
                              isRefreshing ? 'size-4 animate-spin' : 'size-4'
                            }
                          />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Refresh project data</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <TabsTrigger
                          aria-label="Project Settings"
                          value={tab.id}
                        >
                          <SettingsIcon className="size-4" />
                        </TabsTrigger>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Project Settings</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </Fragment>
              )
            }
            return (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.label}
              </TabsTrigger>
            )
          })}
        </TabsList>

        <TabsContent className="space-y-6" value="overview">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start">
            {/* Left column: Details */}
            <div className="space-y-6">
              <Card ref={detailsRef}>
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
                      <span className={`text-sm ${label}`}>Project Types</span>
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
                              <p>{formatDateTime(project.created_at)}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </div>
                    )}

                    <Swap
                      ready={!projectSchemaPending}
                      skeleton={<AttributesSkeleton />}
                    >
                      <ProjectAttributesSection
                        patch={patch}
                        pendingPath={pendingPath}
                        project={project}
                        projectSchema={projectSchema}
                      />
                    </Swap>
                  </div>
                </CardContent>
              </Card>

              {/* Environments — nests here when the right column is taller
                  than Project details; otherwise drops below (see envSpanFull).
                  Rendered even when empty so environments can be added. */}
              {!envSpanFull && (
                <Swap
                  ready={envCardReady}
                  skeleton={
                    <EnvironmentsSkeleton count={sortedEnvironments.length} />
                  }
                >
                  <ProjectEnvironmentsCard
                    deploymentStatus={deploymentStatus}
                    environments={sortedEnvironments}
                    orgSlug={orgSlug}
                    projectId={project.id}
                    projectSchema={projectSchema}
                  />
                </Swap>
              )}
            </div>

            {/* Right column: Health score + Activity. */}
            <div className="flex flex-col gap-6">
              <Card ref={healthRef}>
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
                      <Swap
                        ready={!scoreTrendPending}
                        skeleton={<Sk className="mt-1" h={12} w={90} />}
                      >
                        <ScoreTrendPill
                          liveScore={
                            projectWithBreakdown?.score ?? project.score
                          }
                          scoreTrend={scoreTrend}
                          sessionBaseScore={sessionBaseScore}
                        />
                      </Swap>
                    </div>
                  </div>
                </CardContent>
                {scoreBreakdown &&
                  scoreBreakdown.attribute_contributions.length > 0 && (
                    <CardFooter className="border-tertiary flex-col items-start gap-0 border-t p-0">
                      <button
                        className="text-tertiary hover:text-primary flex w-full items-center justify-between px-6 py-3 text-xs font-medium"
                        onClick={() => setBreakdownOpen((o) => !o)}
                        type="button"
                      >
                        Score breakdown
                        <ChevronDown
                          className={`size-3.5 transition-transform ${breakdownOpen ? 'rotate-180' : ''}`}
                        />
                      </button>
                      {breakdownOpen && (
                        <ScoreBreakdownDetail
                          contributions={scoreBreakdown.attribute_contributions}
                          policies={scoringPolicies}
                          projectSchema={projectSchema}
                        />
                      )}
                    </CardFooter>
                  )}
              </Card>

              <Card
                className="flex min-h-0 flex-col"
                style={{ maxHeight: `${activityMaxHeightPx}px` }}
              >
                <CardHeader
                  className="flex flex-row items-center justify-between"
                  ref={activityHeaderRef}
                >
                  <CardTitle>Recent activity</CardTitle>
                  <button className="text-secondary hover:bg-secondary hover:text-primary inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition-colors">
                    <Filter className="size-3" />
                    Filter
                  </button>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
                  <div ref={activityInnerRef}>
                    <ProjectActivityLog
                      orgSlug={project.team.organization.slug}
                      projectId={project.id}
                      projectSlug={project.slug}
                    />
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Environments — full-width row below both columns when the right
              column is shorter than Project details. */}
          {envSpanFull && (
            <Swap
              ready={envCardReady}
              skeleton={
                <EnvironmentsSkeleton count={sortedEnvironments.length} />
              }
            >
              <ProjectEnvironmentsCard
                deploymentStatus={deploymentStatus}
                environments={sortedEnvironments}
                orgSlug={orgSlug}
                projectId={project.id}
                projectSchema={projectSchema}
              />
            </Swap>
          )}
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
          <DependenciesTab orgSlug={orgSlug} project={project} />
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
        {hasIncidentsPlugin && (
          <TabsContent value="incidents">
            <IncidentsTab orgSlug={orgSlug} projectId={project.id} />
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
        {isReleaseOnly && (
          <TabsContent value="releases">
            {deploymentReadiness === 'disconnected' &&
              resolvedIdentityPlugin && (
                <div className="mb-4">
                  <ConnectIdentityPrompt
                    action="release"
                    label={deploymentConnectLabel}
                    onConnect={() =>
                      navigate(
                        `/settings/connections?connect=${encodeURIComponent(resolvedIdentityPlugin.plugin_slug)}`,
                      )
                    }
                    onManage={() => navigate('/settings/connections')}
                    serviceIcon={deploymentPlugin?.service_icon ?? null}
                  />
                </div>
              )}
            <ReleasesTab orgSlug={orgSlug} project={project} />
          </TabsContent>
        )}
        {hasDeploymentsTab && (
          <TabsContent value="deployments">
            {deploymentReadiness === 'disconnected' &&
              resolvedIdentityPlugin && (
                <div className="mb-4">
                  <ConnectIdentityPrompt
                    action="deploy"
                    label={deploymentConnectLabel}
                    onConnect={() =>
                      navigate(
                        `/settings/connections?connect=${encodeURIComponent(resolvedIdentityPlugin.plugin_slug)}`,
                      )
                    }
                    onManage={() => navigate('/settings/connections')}
                    serviceIcon={deploymentPlugin?.service_icon ?? null}
                  />
                </div>
              )}
            <DeploymentsTab
              canTrigger={canTriggerDeployments}
              connectLabel={deploymentConnectLabel}
              environments={sortedEnvironments}
              onRunStarted={handleRunStarted}
              orgSlug={orgSlug}
              projectId={project.id}
              readiness={deploymentReadiness}
              serviceIcon={deploymentPlugin?.service_icon ?? null}
              serviceLabel={deploymentPlugin?.service_name ?? null}
            />
          </TabsContent>
        )}
        {hasLifecyclePlugin && (
          <TabsContent value="pull-requests">
            <ProjectPullRequestsTab orgSlug={orgSlug} projectId={project.id} />
          </TabsContent>
        )}
        <TabsContent value="score-history">
          <ScoreHistoryTab orgSlug={orgSlug} projectId={project.id} />
        </TabsContent>
        <TabsContent value="doctor">
          <ProjectDoctorTab project={project} />
        </TabsContent>
        <TabsContent value="settings">
          <ProjectSettingsTab project={project} />
        </TabsContent>
      </Tabs>
      {
        // fallow-ignore-next-line complexity
        (() => {
          if (!isDeployModal && !isPromoteModal) return null
          if (!initialSubId) return null
          const targetIdx = sortedEnvironments.findIndex(
            (e) => e.slug === initialSubId,
          )
          if (targetIdx < 0) return null
          const targetEnv = sortedEnvironments[targetIdx]
          const canDeploy = targetEnv?.can_deploy ?? true
          const canPromote = targetEnv?.can_promote ?? false
          // Promote needs an upstream env with a deployed version. When the
          // user lands on /promote/<env> we already short-circuit in the
          // redirect effect above if that's missing — but the modal can
          // still open for /deploy/<env> on an env that *also* supports
          // promote, so we resolve the source here when possible and just
          // omit the Promote tab when prerequisites are unmet.
          const fromSlug =
            targetIdx > 0 ? sortedEnvironments[targetIdx - 1]?.slug : undefined
          const fromCommittish = fromSlug
            ? deploymentStatus[fromSlug]?.committish
            : undefined
          const promoteAvailable =
            canPromote && !!fromSlug && !!fromCommittish && targetIdx > 0
          if (!canDeploy && !promoteAvailable) return null
          return (
            <ReleaseModal
              canDeploy={canDeploy}
              canPromote={promoteAvailable}
              environments={sortedEnvironments}
              fromCommittish={fromCommittish}
              fromEnvironment={fromSlug}
              initialAction={isPromoteModal ? 'promote' : 'deploy'}
              initialEnvSlug={initialSubId}
              onOpenChange={(open) => {
                if (!open) closeModal()
              }}
              onRunStarted={handleRunStarted}
              open={isDeployModal || isPromoteModal}
              orgSlug={orgSlug}
              projectId={project.id}
              projectName={project.name}
            />
          )
        })()
      }
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
      <RelocatePreviewDialog
        entries={relocatePreview?.entries ?? []}
        onCancel={() => setRelocatePreview(null)}
        onConfirm={handleRelocateConfirm}
        open={relocatePreview !== null}
        pending={pendingPath === '/project_type_slugs'}
      />
    </div>
  )
}

function AttributesSkeleton() {
  return (
    <div className="space-y-0">
      {[60, 80, 70].map((w, i) => (
        <div
          className="border-tertiary flex items-center justify-between border-b py-1.5"
          key={i}
        >
          <Sk h={13} w={90} />
          <Sk className="max-w-40" h={13} w={`${w}%`} />
        </div>
      ))}
    </div>
  )
}

// fallow-ignore-next-line complexity
function buildRecommendation(
  c: AttributeContribution,
  policy: ScoringPolicy,
  allowedValues?: Set<string>,
): null | string {
  if (policy.category !== 'attribute') return null
  const current = c.mapped_score
  if (policy.value_score_map) {
    let better = entriesAbove(policy.value_score_map, current)
    // Clip to values the blueprint actually allows for this attribute, so we
    // don't suggest frameworks (or whatever) that aren't pickable anymore.
    // Skip the clip when the blueprint defines no enum for this attribute.
    if (allowedValues && allowedValues.size > 0) {
      better = better.filter(([name]) => allowedValues.has(name))
    }
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
    const better = entriesAbove(policy.range_score_map, current)
    if (better.length === 0) return null
    const [target] = better[0]
    return `Update to reach ${target}`
  }
  return null
}

function entriesAbove(
  map: Record<string, number>,
  current: number,
): [string, number][] {
  return Object.entries(map)
    .filter(([, score]) => score > current)
    .sort(([, a], [, b]) => b - a)
}

function EnvironmentsSkeleton({ count }: { count: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Environments</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-0">
          {Array.from({ length: count }).map((_, i) => (
            <div
              className="border-tertiary border-b py-4 last:border-0"
              key={i}
            >
              <div className="mb-3 flex items-center justify-between">
                <Sk h={16} r={4} w={120} />
                <Sk h={13} w={72} />
              </div>
              <div className="flex gap-6">
                <SkText className="w-28" widths={['50%', '80%']} />
                <SkText className="w-28" widths={['50%', '70%']} />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function fmtAttributeValue(value: unknown): string {
  const n = Number(value)
  return isFinite(n) && String(value).trim() !== ''
    ? String(Math.round(n))
    : String(value)
}

// Label for an integration dashboard link in the header bar: prefer the org
// integration's name, then the name carried on the service edge, then the raw
// slug as a last resort.
function integrationLinkLabel(
  integration: undefined | { name?: null | string },
  svc: { integration_name: null | string; integration_slug: string },
): string {
  return integration?.name || svc.integration_name || svc.integration_slug
}

function LinksSkeleton({ count }: { count: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <span className="flex items-center gap-1.5" key={i}>
          <Sk h={16} r={4} w={16} />
          <Sk h={13} w={72} />
        </span>
      ))}
    </div>
  )
}

// Run the lifecycle preview for a proposed project-type change and return the
// plugins that would relocate. Returns null when this request was superseded
// by a newer commit (its in-flight fetch is aborted so the slower response
// can't reopen the dialog with stale slugs); returns [] when the preview
// merely failed, so the caller falls back to a metadata-only change. The
// abort/supersede handling is irreducibly a few branches for correct request
// cancellation, hence the complexity suppression.
// fallow-ignore-next-line complexity
async function previewRelocations(
  requestRef: { current: AbortController | null },
  orgSlug: string,
  projectId: string,
  slugs: string[],
): Promise<LifecyclePreviewEntry[] | null> {
  requestRef.current?.abort()
  const controller = new AbortController()
  requestRef.current = controller
  try {
    const preview = await previewProjectLifecycle(
      orgSlug,
      projectId,
      slugs,
      controller.signal,
    )
    return preview.previews.filter((p) => p.would_relocate)
  } catch {
    if (controller.signal.aborted) return null
    return []
  }
}

function ScoreBreakdownDetail({
  contributions,
  policies,
  projectSchema,
}: {
  contributions: AttributeContribution[]
  policies: ScoringPolicy[]
  projectSchema?: ProjectSchemaResponse
}) {
  const totalWeight = contributions.reduce((s, c) => s + c.weight, 0)
  const policyBySlug = useMemo(() => {
    const map = new Map<string, ScoringPolicy>()
    for (const p of policies) map.set(p.slug, p)
    return map
  }, [policies])

  // attribute_name -> the set of values the blueprint declares as valid for
  // that attribute. Used to clip score recommendations down to choices the
  // user can actually pick — a policy may score a wider universe than the
  // current blueprint enum (e.g. legacy frameworks that have been pruned).
  // fallow-ignore-next-line complexity
  const allowedValuesByAttribute = useMemo(() => {
    const map = new Map<string, Set<string>>()
    if (!projectSchema) return map
    for (const section of projectSchema.sections) {
      for (const [key, def] of Object.entries(section.properties)) {
        if (def.enum && def.enum.length > 0) {
          map.set(key, new Set(def.enum))
        }
      }
    }
    return map
  }, [projectSchema])

  const enriched = contributions.map((c) => {
    const maxPts = totalWeight > 0 ? (c.weight / totalWeight) * 100 : 0
    return {
      contribution: c,
      isPerfect:
        c.category === 'condition'
          ? c.condition_result === true
          : c.mapped_score >= 100,
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
      <p className="text-tertiary text-[11px]">
        {contributions.length} policies
      </p>
      {improve.length > 0 && (
        <section>
          <div className="text-tertiary mb-2.5 flex items-center justify-between text-[11px] font-semibold tracking-wider uppercase">
            <span>To improve</span>
            <span className="font-mono">{improve.length}</span>
          </div>
          <div className="flex flex-col gap-3">
            {/* fallow-ignore-next-line complexity */}
            {improve.map(({ contribution: c, maxPts, policy }) => {
              const fillPct =
                maxPts > 0 ? (c.weighted_contribution / maxPts) * 100 : 0
              const lost = Math.round(maxPts - c.weighted_contribution)
              const isCondition = c.category === 'condition'
              const policyName = isCondition
                ? policy?.name || formatFieldKey(c.policy_slug)
                : formatFieldKey(c.attribute_name) ||
                  policy?.name ||
                  formatFieldKey(c.policy_slug)
              const recommendation =
                policy && !isCondition
                  ? buildRecommendation(
                      c,
                      policy,
                      allowedValuesByAttribute.get(c.attribute_name),
                    )
                  : null
              return (
                <div
                  className="border-tertiary bg-primary rounded-md border p-3.5"
                  key={c.policy_slug}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex min-w-0 items-baseline gap-1.5">
                      <span className="text-primary text-[14px] font-semibold">
                        {policyName}
                      </span>
                      <span className="text-tertiary font-mono text-[11px]">
                        w{c.weight}
                      </span>
                    </div>
                    <div className="shrink-0 font-mono text-[13px] tabular-nums">
                      <span className="text-primary font-semibold">
                        {Math.round(c.weighted_contribution)}
                      </span>
                      <span className="text-tertiary">
                        {' '}
                        / {Math.round(maxPts)}
                      </span>
                    </div>
                  </div>
                  {isCondition ? (
                    <div className="text-secondary mt-1 mb-2.5 text-[13px]">
                      <p>
                        {policy?.description || 'Condition'}{' '}
                        <span className="text-danger font-medium">
                          {c.condition_result === false
                            ? '· not met'
                            : '· not evaluated'}
                        </span>
                      </p>
                      {c.matched_neighbours &&
                        c.matched_neighbours.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            {c.matched_neighbours.map((n) => (
                              <span
                                className="bg-danger text-danger inline-flex items-center rounded px-1.5 py-0.5 text-[12px] font-medium"
                                key={n.id}
                              >
                                {n.name || n.slug || n.id}
                              </span>
                            ))}
                          </div>
                        )}
                    </div>
                  ) : (
                    <p className="text-secondary mt-1 mb-2.5 text-[13px]">
                      Currently{' '}
                      <span className="text-amber-text font-medium">
                        {c.value != null
                          ? fmtAttributeValue(c.value)
                          : 'Not set'}
                      </span>
                    </p>
                  )}
                  <div className="bg-secondary relative h-1.5 rounded-full">
                    {fillPct > 0 && (
                      <div
                        className="bg-action absolute inset-y-0 left-0 rounded-full"
                        style={{ width: `${fillPct}%` }}
                      />
                    )}
                  </div>
                  <div className="text-secondary mt-2 flex items-center gap-1.5 text-[12.5px]">
                    <TrendingDown className="text-tertiary size-3 shrink-0" />
                    <span>
                      Losing{' '}
                      <span className="text-danger font-mono font-medium">
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
          <div className="text-tertiary mb-2.5 flex items-center justify-between text-[11px] font-semibold tracking-wider uppercase">
            <span>At maximum</span>
            <span className="font-mono">{perfect.length}</span>
          </div>
          <div className="border-tertiary overflow-hidden rounded-md border">
            {/* fallow-ignore-next-line complexity */}
            {perfect.map(({ contribution: c, maxPts, policy }, idx) => {
              const isCondition = c.category === 'condition'
              const policyName = isCondition
                ? policy?.name || formatFieldKey(c.policy_slug)
                : formatFieldKey(c.attribute_name) ||
                  policy?.name ||
                  formatFieldKey(c.policy_slug)
              return (
                <div
                  className={`bg-primary grid grid-cols-[auto_1fr_auto] items-center gap-2.5 px-3 py-2.5 ${
                    idx > 0 ? 'border-tertiary border-t' : ''
                  }`}
                  key={c.policy_slug}
                >
                  <span className="bg-success text-success inline-flex size-4 items-center justify-center rounded-full">
                    <Check className="size-2.5" strokeWidth={3} />
                  </span>
                  <span className="text-primary text-[13.5px] font-medium">
                    {policyName}
                    <span className="text-tertiary ml-1.5 font-normal">
                      {isCondition
                        ? 'met'
                        : c.value != null
                          ? fmtAttributeValue(c.value)
                          : 'Not set'}
                    </span>
                  </span>
                  <span className="text-tertiary font-mono text-[12px] tabular-nums">
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

// fallow-ignore-next-line complexity
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
    <p className="text-tertiary font-mono text-xs">
      {delta > 0 ? '+' : ''}
      {Math.round(delta)} pts / {trendLabel}
    </p>
  )
}
