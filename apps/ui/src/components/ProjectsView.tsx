import * as React from 'react'
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { useNavigate, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  ChevronDown,
  ChevronsUpDown,
  ChevronUp,
  CircleCheck,
  GitPullRequest,
  Grid3x3,
  List,
  ListFilter,
  Plus,
  RefreshCw,
  Search,
  User,
} from 'lucide-react'
import { matchSorter } from 'match-sorter'

import { getProjectsSlim, type ProjectListItem } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { deriveChipColors } from '@/lib/chip-colors'
import { formatRelativeDate } from '@/lib/formatDate'

import { NewProjectDialog } from './NewProjectDialog'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { Checkbox } from './ui/checkbox'
import { EnvironmentBadge } from './ui/environment-badge'
import { HoverCard, HoverCardContent, HoverCardTrigger } from './ui/hover-card'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { ScoreBadge } from './ui/score-badge'

interface DriftPair {
  drifted: boolean
  from: string
  to: string
  toLabelColor?: null | string
}

interface FilterHeaderProps {
  activeFilters: Set<string>
  centerFilter?: FilterPopoverProps & { title: string }
  children: React.ReactNode
  className?: string
  hideMainFilter?: boolean
  label: string
  onSort: () => void
  onToggle: (slug: string) => void
  options: { label: string; slug: string }[]
  rightFilter?: FilterPopoverProps & { title: string }
  sortDir: SortDir
  sorted: boolean
}

interface FilterPopoverProps {
  activeFilters: Set<string>
  label: string
  onToggle: (slug: string) => void
  options: { label: string; slug: string }[]
}

interface ProjectListRowProps {
  onSelect: (id: string) => void
  project: ProjectListItem
}

type SortDir = 'asc' | 'desc'

interface SortHeaderProps {
  children: React.ReactNode
  className?: string
  onSort: () => void
  sortDir: SortDir
  sorted: boolean
}

type SortKey = 'name' | 'prs' | 'score' | 'team' | 'type'

const VIEW_MODE_STORAGE_KEY = 'imbi.projects.view-mode'

// Trails the user by ~one settle so the URL ``?q=`` write (and the
// downstream filter+render pass) doesn't fire on every keystroke.
// 200ms is short enough to feel synchronous for the common
// type-pause-look pattern.
const SEARCH_DEBOUNCE_MS = 200

// fallow-ignore-next-line complexity
export function ProjectsView() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const [storedView] = useState(() =>
    typeof window === 'undefined'
      ? null
      : window.localStorage.getItem(VIEW_MODE_STORAGE_KEY),
  )
  const rawView = searchParams.get('view')
  const viewMode = resolveViewMode(rawView, storedView)
  // ``inputQuery`` drives the controlled <Input>; ``debouncedQuery``
  // is what gets persisted to the URL and consumed by the filter
  // pipeline. Local input state keeps typing responsive even though
  // filtering hundreds of rows is expensive; the URL sync trails the
  // user by ``SEARCH_DEBOUNCE_MS`` so back-buttoning still works.
  const urlQuery = searchParams.get('q') ?? ''
  const [inputQuery, setInputQuery] = useState(urlQuery)
  const debouncedQuery = useDebouncedValue(inputQuery, SEARCH_DEBOUNCE_MS)
  // ``useDeferredValue`` lets React render the stale filtered list
  // first (so the input never freezes), then reconcile to the new
  // ``debouncedQuery`` at a lower priority. Cheap to add and
  // additive to the debounce.
  const deferredQuery = useDeferredValue(debouncedQuery)
  const sortKey = (searchParams.get('sort') ?? 'name') as SortKey
  const sortDir = (searchParams.get('dir') ?? 'asc') as SortDir
  const teamsParam = searchParams.get('teams') ?? ''
  const typesParam = searchParams.get('types') ?? ''
  const driftsParam = searchParams.get('drifts') ?? ''
  const hasDrift = searchParams.get('has_drift') === '1'
  const hasOpenPRs = searchParams.get('has_open_prs') === '1'
  const hasMyOpenPRs = searchParams.get('has_my_open_prs') === '1'

  const setViewMode = (v: 'grid' | 'list') => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, v)
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('view', v)
        return next
      },
      { replace: true },
    )
  }

  // Sync the debounced query → URL. Skip the write when the value
  // already matches what's in the URL (covers back/forward and the
  // initial mount where ``inputQuery === urlQuery`` by construction).
  useEffect(() => {
    if (debouncedQuery === urlQuery) return
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (debouncedQuery) next.set('q', debouncedQuery)
        else next.delete('q')
        return next
      },
      { replace: true },
    )
  }, [debouncedQuery, urlQuery, setSearchParams])

  // Honor external URL changes (back/forward, deep links) by
  // resyncing the input. Compares against the *current* input so
  // typing isn't clobbered by the debounced URL write that just
  // landed.
  useEffect(() => {
    if (urlQuery !== inputQuery && urlQuery !== debouncedQuery) {
      setInputQuery(urlQuery)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery])

  const setSort = (key: SortKey) =>
    setSearchParams((prev) => nextSortParams(prev, key), { replace: true })

  const toggleBoolParam = (key: string) => () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (prev.get(key) === '1') next.delete(key)
        else next.set(key, '1')
        return next
      },
      { replace: true },
    )
  const toggleDrift = toggleBoolParam('has_drift')
  const toggleOpenPRs = toggleBoolParam('has_open_prs')
  const toggleMyOpenPRs = toggleBoolParam('has_my_open_prs')

  const toggleFilter = (param: string, slug: string) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        const current = new Set(
          prev.get(param)?.split(',').filter(Boolean) ?? [],
        )
        if (current.has(slug)) current.delete(slug)
        else current.add(slug)
        if (current.size > 0) next.set(param, [...current].sort().join(','))
        else next.delete(param)
        return next
      },
      { replace: true },
    )

  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)

  const {
    data: projects,
    isFetching,
    isLoading,
    refetch,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['projects', orgSlug, 'slim'],
  })

  const teamOptions = useMemo(
    () =>
      Array.from(
        new Map(
          (projects ?? []).map((p) => [p.team.slug, p.team.name]),
        ).entries(),
      )
        .map(([slug, label]) => ({ label, slug }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [projects],
  )

  // fallow-ignore-next-line complexity
  const typeOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of projects ?? []) {
      for (const pt of p.project_types ?? []) {
        map.set(pt.slug, pt.name)
      }
    }
    return Array.from(map.entries())
      .map(([slug, label]) => ({ label, slug }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [projects])

  // Stable ref so the memoized ``ProjectListRow`` can actually skip
  // re-renders when only the parent's input/filter state changes.
  const handleProjectSelect = useCallback(
    (projectId: string) => {
      navigate(`/projects/${projectId}`)
    },
    [navigate],
  )

  const driftedProjectIds = useMemo(() => {
    const ids = new Set<string>()
    for (const p of projects ?? []) if (projectHasDrift(p)) ids.add(p.id)
    return ids
  }, [projects])
  const totalDriftProjects = driftedProjectIds.size

  // fallow-ignore-next-line complexity
  const filteredProjects = useMemo(() => {
    const teamSet = new Set(teamsParam.split(',').filter(Boolean))
    const typeSet = new Set(typesParam.split(',').filter(Boolean))
    const driftSet = new Set(driftsParam.split(',').filter(Boolean))
    let all = projects ?? []

    if (teamSet.size > 0) {
      all = all.filter((p) => teamSet.has(p.team.slug))
    }
    if (typeSet.size > 0) {
      all = all.filter((p) =>
        (p.project_types ?? []).some((pt) => typeSet.has(pt.slug)),
      )
    }
    if (driftSet.size > 0) {
      all = all.filter((p) =>
        driftSet.has('none') ? !driftedProjectIds.has(p.id) : true,
      )
    }
    if (hasOpenPRs) {
      all = all.filter((p) => (p.open_pr_count ?? 0) > 0)
    }
    if (hasMyOpenPRs) {
      all = all.filter((p) => (p.viewer_open_pr_count ?? 0) > 0)
    }
    if (hasDrift) {
      all = all.filter((p) => driftedProjectIds.has(p.id))
    }
    if (deferredQuery) {
      return matchSorter(all, deferredQuery, {
        keys: [
          'name',
          'description',
          'team.name',
          { key: (p) => (p.project_types || []).map((pt) => pt.name) },
        ],
      })
    }
    // Case-insensitive collation so "AWeber" and "aws-foo" don't end up
    // ordered before "Account" via JS's default locale-strength tiebreak.
    // Names get trimmed because some legacy data carries leading
    // whitespace that would otherwise float those rows to the top.
    const collator = new Intl.Collator('en', { sensitivity: 'base' })
    const key = (s: null | string | undefined) => (s ?? '').trim()

    // fallow-ignore-next-line complexity
    return [...all].sort((a, b) => {
      let cmp = 0
      if (sortKey === 'name') cmp = collator.compare(key(a.name), key(b.name))
      else if (sortKey === 'team')
        cmp = collator.compare(key(a.team.name), key(b.team.name))
      else if (sortKey === 'type') {
        const aType = (a.project_types ?? [])[0]?.name ?? ''
        const bType = (b.project_types ?? [])[0]?.name ?? ''
        cmp = collator.compare(key(aType), key(bType))
      } else if (sortKey === 'prs')
        cmp = (a.open_pr_count ?? 0) - (b.open_pr_count ?? 0)
      else if (sortKey === 'score') cmp = (a.score ?? 0) - (b.score ?? 0)
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [
    projects,
    driftedProjectIds,
    deferredQuery,
    sortKey,
    sortDir,
    teamsParam,
    typesParam,
    driftsParam,
    hasDrift,
    hasOpenPRs,
    hasMyOpenPRs,
  ])

  const totalOpenPRs = useMemo(
    () => (projects ?? []).reduce((sum, p) => sum + (p.open_pr_count ?? 0), 0),
    [projects],
  )
  const totalMyOpenPRs = useMemo(
    () =>
      (projects ?? []).reduce(
        (sum, p) => sum + (p.viewer_open_pr_count ?? 0),
        0,
      ),
    [projects],
  )

  const activeTeamSet = new Set(teamsParam.split(',').filter(Boolean))
  const activeTypeSet = new Set(typesParam.split(',').filter(Boolean))
  const activeDriftSet = new Set(driftsParam.split(',').filter(Boolean))
  const driftOptions = [{ label: 'None', slug: 'none' }]

  return (
    <div className="mx-auto max-w-screen-2xl px-6 py-8">
      <div className="mb-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-primary text-2xl font-semibold">Projects</h1>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={() => setNewProjectDialogOpen(true)}
            size="sm"
          >
            <Plus className="mr-2 size-4" />
            New Project
          </Button>
        </div>

        {/* Search and Filters */}
        <Card className="p-4">
          <div className="flex items-center gap-3">
            <div className="relative w-80 shrink-0">
              <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                className="pl-9"
                disabled={isLoading}
                onChange={(e) => setInputQuery(e.target.value)}
                placeholder="Search projects..."
                type="text"
                value={inputQuery}
              />
            </div>

            <div className="flex flex-1 items-center gap-2">
              <StatBadge hidden label="Healthy" value={0} variant="success" />
              <StatBadge hidden label="Deploying" value={0} variant="warning" />
              <StatBadge hidden label="Failed" value={0} variant="danger" />
              <StatBadge
                active={hasOpenPRs}
                disabled={isLoading}
                label="Open PRs"
                onClick={toggleOpenPRs}
                value={totalOpenPRs}
                variant="accent"
              />
              <StatBadge
                active={hasDrift}
                disabled={isLoading}
                label="Need Release"
                onClick={toggleDrift}
                value={totalDriftProjects}
                variant="amber"
              />
              <StatBadge
                active={hasMyOpenPRs}
                disabled={isLoading}
                label="My PRs"
                onClick={toggleMyOpenPRs}
                value={totalMyOpenPRs}
                variant="info"
              />
            </div>

            <div className="border-secondary flex items-center overflow-hidden rounded-lg border">
              <Button
                aria-label="List view"
                className={`rounded-r-none ${viewMode === 'list' ? 'bg-amber-bg text-amber-text' : ''}`}
                disabled={isLoading}
                onClick={() => setViewMode('list')}
                size="sm"
                variant="ghost"
              >
                <List className="size-4" />
              </Button>
              <Button
                aria-label="Grid view"
                className={`rounded-l-none ${viewMode === 'grid' ? 'bg-amber-bg text-amber-text' : ''}`}
                disabled={isLoading}
                onClick={() => setViewMode('grid')}
                size="sm"
                variant="ghost"
              >
                <Grid3x3 className="size-4" />
              </Button>
            </div>

            <div className="border-secondary flex items-center overflow-hidden rounded-lg border">
              <Button
                aria-label="Refresh"
                disabled={isFetching || isLoading}
                onClick={() => refetch()}
                size="sm"
                variant="ghost"
              >
                <RefreshCw
                  className={`size-4${isFetching ? ' animate-spin' : ''}`}
                />
              </Button>
            </div>
          </div>
        </Card>
      </div>
      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <div className="text-tertiary text-lg">Loading projects...</div>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {/* fallow-ignore-next-line complexity */}
          {filteredProjects.map((project) => {
            const typeNames = (project.project_types ?? [])
              .map((pt) => pt.name)
              .join(', ')
            const meta = [typeNames, project.team.name]
              .filter(Boolean)
              .join(' · ')
            const envs = [...(project.environments ?? [])].sort(
              (a, b) =>
                (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
                a.name.localeCompare(b.name),
            )
            return (
              <Card
                className="flex min-h-56 cursor-pointer flex-col p-5 transition-shadow hover:shadow-md"
                key={`card-${project.id}`}
                onClick={() => handleProjectSelect(project.id)}
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-primary mb-1 truncate font-medium">
                      {project.name}
                    </h3>
                    <p className="text-tertiary text-sm">{meta}</p>
                  </div>
                  <ScoreBadge
                    score={project.score}
                    size="md"
                    variant="circle"
                  />
                </div>

                {project.description && (
                  <p className="text-secondary line-clamp-2 text-sm">
                    {project.description}
                  </p>
                )}

                <div className="border-tertiary mt-auto border-t pt-[18px]">
                  <div className="flex min-h-8 flex-wrap items-center gap-2">
                    <span
                      className={`border-accent bg-accent text-accent inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs ${(project.open_pr_count ?? 0) > 0 ? '' : 'invisible'}`}
                    >
                      <GitPullRequest className="size-3.5" />
                      <span>{project.open_pr_count ?? 0}</span>
                    </span>
                    <span
                      className={`border-info bg-info text-info inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs ${(project.viewer_open_pr_count ?? 0) > 0 ? '' : 'invisible'}`}
                    >
                      <User className="size-3.5" />
                      <span>{project.viewer_open_pr_count ?? 0}</span>
                    </span>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <DriftCell inline project={project} />
                    </div>
                    {isProjectDeployable(project) && envs.length > 0 && (
                      <div className="ml-auto flex flex-wrap items-center gap-2">
                        {envs.map((env) => (
                          <EnvDeploymentHover
                            env={env}
                            key={env.slug}
                            release={(project.current_releases ?? {})[env.slug]}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <div className="border-tertiary bg-secondary text-secondary flex items-stretch border-b text-sm font-medium">
            <FilterHeader
              activeFilters={activeTeamSet}
              centerFilter={{
                activeFilters: activeTeamSet,
                label: 'team',
                onToggle: (s) => toggleFilter('teams', s),
                options: teamOptions,
                title: 'Team',
              }}
              className="w-65 shrink-0"
              hideMainFilter
              label="team"
              onSort={() => setSort('name')}
              onToggle={(s) => toggleFilter('teams', s)}
              options={teamOptions}
              rightFilter={{
                activeFilters: activeTypeSet,
                label: 'type',
                onToggle: (s) => toggleFilter('types', s),
                options: typeOptions,
                title: 'Type',
              }}
              sortDir={sortDir}
              sorted={sortKey === 'name'}
            >
              Project
            </FilterHeader>
            <SortHeader
              className="w-40 shrink-0 text-center whitespace-nowrap"
              onSort={() => setSort('prs')}
              sortDir={sortDir}
              sorted={sortKey === 'prs'}
            >
              PRs
            </SortHeader>
            <div className="w-40 shrink-0 px-2.5 py-3 text-center whitespace-nowrap">
              <div className="flex items-center justify-center gap-1 text-center">
                Drift
                <FilterPopover
                  activeFilters={activeDriftSet}
                  label="drift"
                  onToggle={(s) => toggleFilter('drifts', s)}
                  options={driftOptions}
                />
              </div>
            </div>
            <div className="min-w-0 flex-1 px-6 py-3 text-center whitespace-nowrap">
              Current Deployments
            </div>
            <SortHeader
              className="w-40 shrink-0 text-center whitespace-nowrap"
              onSort={() => setSort('score')}
              sortDir={sortDir}
              sorted={sortKey === 'score'}
            >
              Health Score
            </SortHeader>
          </div>
          <div
            className="divide-tertiary divide-y overflow-y-auto"
            style={{
              maxHeight: 'calc(100vh - 330px - var(--assistant-height, 64px))',
            }}
          >
            {filteredProjects.map((project) => (
              <ProjectListRow
                key={`row-${project.id}`}
                onSelect={handleProjectSelect}
                project={project}
              />
            ))}
          </div>
        </Card>
      )}
      {!isLoading && filteredProjects.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-tertiary">
            No projects found matching your criteria
          </p>
        </div>
      )}
      <NewProjectDialog
        isOpen={newProjectDialogOpen}
        onClose={() => setNewProjectDialogOpen(false)}
        onProjectCreated={(id) => navigate(`/projects/${id}`)}
      />
    </div>
  )
}

function abbreviateEnvName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return ''
  if (parts.length === 1) return parts[0][0]!.toUpperCase()
  return parts.map((w) => w[0]!.toUpperCase()).join('')
}

// fallow-ignore-next-line complexity
function computeDriftPairs(
  environments: {
    label_color?: null | string
    name: string
    slug: string
    sort_order?: null | number
  }[],
  releases: Record<string, { committish?: null | string; tag?: null | string }>,
): DriftPair[] {
  const sorted = [...environments].sort(
    (a, b) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name),
  )
  const pairs: DriftPair[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    const a = sorted[i]
    const b = sorted[i + 1]
    const ra = releases[a.slug]
    const rb = releases[b.slug]
    const aTag = ra?.tag ?? null
    const bTag = rb?.tag ?? null
    const aSha = ra?.committish ?? null
    const bSha = rb?.committish ?? null
    // When both envs have a SHA, compare them directly so that a tag-only
    // difference on identical commits does not register as drift. Otherwise
    // fall back to tag-or-SHA equality.
    const drifted =
      aSha && bSha ? aSha !== bSha : (aTag ?? aSha) !== (bTag ?? bSha)
    pairs.push({
      drifted,
      from: a.name,
      to: b.name,
      toLabelColor: b.label_color ?? null,
    })
  }
  return pairs
}

function DeploymentCards({
  environments,
  releases,
}: {
  environments: {
    label_color?: null | string
    name: string
    slug: string
    sort_order?: null | number
  }[]
  releases: Record<
    string,
    {
      committish?: null | string
      deployed_at: string
      performed_by?: null | string
      tag?: null | string
    }
  >
}) {
  const sorted = [...environments].sort(
    (a, b) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name),
  )
  return (
    <div className="flex items-start gap-2" style={{ flexWrap: 'nowrap' }}>
      {/* fallow-ignore-next-line complexity */}
      {sorted.map((env, idx) => {
        const release = releases[env.slug]
        const derived = env.label_color
          ? deriveChipColors(env.label_color, false)
          : null
        const cardClass = derived
          ? `w-50 rounded-lg border px-3 py-2${!release ? ' border-dashed opacity-60' : ''}`
          : `w-50 rounded-lg border px-3 py-2${release ? ' border-border bg-card' : ' border-tertiary/40 border-dashed opacity-60'}`
        const cardStyle = derived
          ? { backgroundColor: derived.bg, borderColor: derived.border }
          : undefined
        return (
          <span className="flex shrink-0 items-center" key={env.slug}>
            {idx > 0 && (
              <ArrowRight className="text-tertiary mx-2 size-3.5 shrink-0" />
            )}
            <span className={cardClass} style={cardStyle}>
              <p className="text-secondary mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={
                    env.label_color
                      ? { backgroundColor: env.label_color }
                      : undefined
                  }
                />
                {env.name}
              </p>
              <p className="flex items-center gap-2 font-mono text-base leading-tight">
                <ReleaseLabel release={release} />
              </p>
              <p className="text-tertiary mt-1 flex items-center justify-between text-xs">
                {release ? (
                  <>
                    <span>{release.performed_by ?? ''}</span>
                    <span>{formatRelativeDate(release.deployed_at)}</span>
                  </>
                ) : (
                  <span className="invisible">—</span>
                )}
              </p>
            </span>
          </span>
        )
      })}
    </div>
  )
}

// fallow-ignore-next-line complexity
function DriftCell({
  inline,
  project,
}: {
  inline?: boolean
  project: {
    current_releases?: null | Record<
      string,
      { committish?: null | string; tag?: null | string }
    >
    environments?:
      | null
      | {
          label_color?: null | string
          name: string
          slug: string
          sort_order?: null | number
        }[]
    project_types?: null | object[]
  }
}) {
  const { isDarkMode } = useTheme()
  if (!isProjectDeployable(project)) return null
  const envs = project.environments ?? []
  if (envs.length < 2) {
    return null
  }
  const pairs = computeDriftPairs(envs, project.current_releases ?? {})
  const drifted = pairs.filter((p) => p.drifted)
  if (drifted.length === 0) {
    return null
  }
  const containerCls = inline
    ? 'flex flex-row flex-wrap items-center gap-1'
    : 'flex flex-col items-center gap-1.5'
  const badgeBaseCls = inline
    ? 'inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-mono text-xs'
    : 'inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-xs'
  const fallbackCls = 'border-amber-border bg-amber-bg text-amber-text border'
  return (
    <div className={containerCls}>
      {drifted.map((p) => {
        const derived = p.toLabelColor
          ? deriveChipColors(p.toLabelColor, isDarkMode)
          : null
        return (
          <span
            className={
              derived
                ? `${badgeBaseCls} border`
                : `${badgeBaseCls} ${fallbackCls}`
            }
            key={`${p.from}->${p.to}`}
            style={
              derived
                ? {
                    backgroundColor: derived.bg,
                    borderColor: derived.border,
                    color: derived.fg,
                  }
                : undefined
            }
          >
            <span className="font-medium">Δ</span>
            <span>{abbreviateEnvName(p.from)}</span>
            <span>→</span>
            <span>{abbreviateEnvName(p.to)}</span>
          </span>
        )
      })}
    </div>
  )
}

// fallow-ignore-next-line complexity
function EnvDeploymentHover({
  env,
  release,
}: {
  env: {
    label_color?: null | string
    name: string
    slug: string
    sort_order?: null | number
  }
  release?: {
    committish?: null | string
    deployed_at: string
    performed_by?: null | string
    tag?: null | string
  }
}) {
  const { isDarkMode } = useTheme()
  const derived = env.label_color
    ? deriveChipColors(env.label_color, isDarkMode)
    : null
  const cardStyle = derived
    ? { backgroundColor: derived.bg, borderColor: derived.border }
    : undefined
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <span>
          <EnvironmentBadge
            label_color={env.label_color}
            name={env.name}
            slug={env.slug}
          />
        </span>
      </HoverCardTrigger>
      <HoverCardContent align="center" className="w-55 overflow-hidden p-0">
        <div className="p-3" style={cardStyle}>
          <p className="text-secondary mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <span
              className="size-2 shrink-0 rounded-full"
              style={
                env.label_color
                  ? { backgroundColor: env.label_color }
                  : undefined
              }
            />
            {env.name}
          </p>
          <p className="flex items-center gap-2 font-mono text-base leading-tight font-bold">
            <ReleaseLabel release={release} />
            {release && (
              <CircleCheck className="text-success size-4 shrink-0" />
            )}
          </p>
          <p className="text-tertiary mt-1 flex items-center justify-between text-xs">
            {release ? (
              <>
                <span>{release.performed_by ?? ''}</span>
                <span>{formatRelativeDate(release.deployed_at)}</span>
              </>
            ) : (
              <span className="invisible">—</span>
            )}
          </p>
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

// fallow-ignore-next-line complexity
function FilterHeader({
  activeFilters,
  centerFilter,
  children,
  className,
  hideMainFilter,
  label,
  onSort,
  onToggle,
  options,
  rightFilter,
  sortDir,
  sorted,
}: FilterHeaderProps) {
  return (
    <div className={`px-6 py-3${className ? ` ${className}` : ''}`}>
      <div className="flex items-center justify-between gap-0.5">
        <div className="flex items-center gap-0.5">
          <button
            className="hover:text-primary inline-flex items-center gap-1"
            onClick={onSort}
            type="button"
          >
            {children}
            {sorted ? (
              sortDir === 'asc' ? (
                <ChevronUp className="size-3.5 shrink-0" />
              ) : (
                <ChevronDown className="size-3.5 shrink-0" />
              )
            ) : (
              <ChevronsUpDown className="text-tertiary/50 size-3.5 shrink-0" />
            )}
          </button>
          {!hideMainFilter && (
            <FilterPopover
              activeFilters={activeFilters}
              label={label}
              onToggle={onToggle}
              options={options}
            />
          )}
        </div>
        {centerFilter && (
          <div className="flex items-center gap-1">
            <span className="text-tertiary text-sm font-medium">
              {centerFilter.title}
            </span>
            <FilterPopover {...centerFilter} />
          </div>
        )}
        {rightFilter && (
          <div className="flex items-center gap-1">
            <span className="text-tertiary text-sm font-medium">
              {rightFilter.title}
            </span>
            <FilterPopover {...rightFilter} />
          </div>
        )}
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function FilterPopover({
  activeFilters,
  label,
  onToggle,
  options,
}: FilterPopoverProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className={`flex items-center gap-0.5 rounded px-0.5 py-0.5 ${
            activeFilters.size > 0
              ? 'text-action'
              : 'text-tertiary/50 hover:text-secondary'
          }`}
          type="button"
        >
          <ListFilter className="size-3.5" />
          {activeFilters.size > 0 && (
            <span className="text-xs leading-none">{activeFilters.size}</span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-48 p-2">
        <p className="text-secondary mb-2 px-1 text-xs font-medium tracking-wide uppercase">
          Filter by {label}
        </p>
        <div className="space-y-0.5">
          {options.map((opt) => (
            <Label
              className="hover:bg-secondary flex cursor-pointer items-center gap-2 rounded px-1 py-1.5"
              key={opt.slug}
            >
              <Checkbox
                checked={activeFilters.has(opt.slug)}
                onCheckedChange={() => onToggle(opt.slug)}
              />
              <span className="text-primary text-sm">{opt.label}</span>
            </Label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function isProjectDeployable(project: {
  project_types?: null | object[]
}): boolean {
  return (project.project_types ?? []).some(
    (pt) => (pt as { deployable?: boolean }).deployable === true,
  )
}

// fallow-ignore-next-line complexity
function nextSortParams(prev: URLSearchParams, key: SortKey): URLSearchParams {
  const next = new URLSearchParams(prev)
  const curKey = (prev.get('sort') ?? 'name') as SortKey
  const curDir = (prev.get('dir') ?? 'asc') as SortDir
  const flipping = curKey === key && curDir === 'asc'
  const nextDir: SortDir = flipping ? 'desc' : 'asc'
  // Keep the URL clean when reverting to the default (name asc).
  const isDefault = key === 'name' && nextDir === 'asc'
  if (isDefault) {
    next.delete('sort')
    next.delete('dir')
    return next
  }
  next.set('sort', key)
  next.set('dir', nextDir)
  return next
}

// fallow-ignore-next-line complexity
function projectHasDrift(project: {
  current_releases?: null | Record<
    string,
    { committish?: null | string; tag?: null | string }
  >
  environments?:
    | null
    | {
        label_color?: null | string
        name: string
        slug: string
        sort_order?: null | number
      }[]
  project_types?: null | object[]
}): boolean {
  if (!isProjectDeployable(project)) return false
  const envs = project.environments ?? []
  if (envs.length < 2) return false
  const pairs = computeDriftPairs(envs, project.current_releases ?? {})
  return pairs.some((p) => p.drifted)
}

// fallow-ignore-next-line complexity
function ReleaseLabel({
  release,
}: {
  release?: null | {
    committish?: null | string
    tag?: null | string
  }
}) {
  return (
    <span className="min-w-0 flex-1">
      {release ? (
        <>
          <span className="text-primary">
            {release.tag ?? release.committish ?? '—'}
          </span>
          {release.tag && release.committish && (
            <span className="text-tertiary ml-2 text-xs font-normal">
              {release.committish}
            </span>
          )}
        </>
      ) : (
        <span className="text-tertiary text-sm font-normal">Not deployed</span>
      )}
    </span>
  )
}

// fallow-ignore-next-line complexity
function resolveViewMode(
  raw: null | string,
  stored: null | string,
): 'grid' | 'list' {
  if (raw === 'grid' || raw === 'list') return raw
  if (stored === 'grid' || stored === 'list') return stored
  return 'list'
}

function SortHeader({
  children,
  className,
  onSort,
  sortDir,
  sorted,
}: SortHeaderProps) {
  return (
    <div
      className={`hover:text-primary cursor-pointer px-6 py-3 select-none ${className ? ` ${className}` : ''}`}
      onClick={onSort}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sorted ? (
          sortDir === 'asc' ? (
            <ChevronUp className="size-3.5 shrink-0" />
          ) : (
            <ChevronDown className="size-3.5 shrink-0" />
          )
        ) : (
          <ChevronsUpDown className="text-tertiary/50 size-3.5 shrink-0" />
        )}
      </span>
    </div>
  )
}

// fallow-ignore-next-line complexity
function StatBadge({
  active,
  disabled,
  hidden,
  label,
  onClick,
  value,
  variant,
}: {
  active?: boolean
  disabled?: boolean
  hidden?: boolean
  label: string
  onClick?: () => void
  value: number
  variant?:
    | 'accent'
    | 'amber'
    | 'danger'
    | 'info'
    | 'success'
    | 'teal'
    | 'warning'
}) {
  if (hidden) return null
  const variantCls =
    variant === 'success'
      ? 'bg-success border-success text-success'
      : variant === 'warning'
        ? 'bg-warning border-warning text-warning'
        : variant === 'danger'
          ? 'bg-danger border-danger text-danger'
          : variant === 'accent'
            ? 'bg-accent border-accent text-accent'
            : variant === 'info'
              ? 'bg-info border-info text-info'
              : variant === 'teal'
                ? 'bg-teal border-teal text-teal'
                : variant === 'amber'
                  ? 'bg-amber-bg border-amber-border text-amber-text'
                  : 'border-secondary text-secondary'
  const interactiveCls = onClick
    ? disabled
      ? 'cursor-not-allowed opacity-50'
      : `cursor-pointer transition-shadow${active ? ' ring-2 ring-current ring-offset-2 ring-offset-background' : ' hover:ring-1 hover:ring-current hover:ring-offset-1 hover:ring-offset-background'}`
    : ''
  const content = (
    <>
      <span className={variant ? 'font-medium' : 'text-primary font-medium'}>
        {value}
      </span>
      <span>{label}</span>
    </>
  )
  const cls = `inline-flex h-10 items-center gap-1.5 rounded-md border p-3 text-xs ${variantCls} ${interactiveCls}`
  if (onClick) {
    return (
      <button
        aria-pressed={active}
        className={cls}
        disabled={disabled}
        onClick={onClick}
        type="button"
      >
        {content}
      </button>
    )
  }
  return <span className={cls}>{content}</span>
}

// Memoized list-mode row so a parent re-render (e.g. an ``inputQuery``
// keystroke) doesn't redo the JSX for every row in the table. The
// ``project`` reference comes from a memoized filter pipeline, so as
// long as the underlying object identity is stable (it is — React Query
// returns the same array between renders), the row skips its render.
// fallow-ignore-next-line complexity
const ProjectListRow = React.memo(function ProjectListRow({
  onSelect,
  project,
}: ProjectListRowProps) {
  return (
    <div
      className="hover:bg-secondary flex cursor-pointer items-center transition-colors"
      onClick={() => onSelect(project.id)}
    >
      <div className="w-65 shrink-0 px-6 py-4">
        <p className="text-primary font-medium">{project.name}</p>
        {(project.project_types ?? []).length > 0 && (
          <p className="text-secondary text-xs">
            {project.project_types!.map((pt) => pt.name).join(', ')}
          </p>
        )}
        <p className="text-tertiary text-xs">{project.team.name}</p>
      </div>
      <div className="w-40 shrink-0 px-6 py-4 whitespace-nowrap">
        <div className="flex items-center justify-center gap-1.5">
          {(project.open_pr_count ?? 0) > 0 && (
            <span className="border-accent bg-accent text-accent inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs">
              <GitPullRequest className="size-3.5" />
              <span>{project.open_pr_count}</span>
            </span>
          )}
          {(project.viewer_open_pr_count ?? 0) > 0 && (
            <span className="border-info bg-info text-info inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs">
              <User className="size-3.5" />
              <span>{project.viewer_open_pr_count}</span>
            </span>
          )}
        </div>
      </div>
      <div className="flex w-40 shrink-0 items-center justify-center px-5 py-4">
        <DriftCell project={project} />
      </div>
      <div
        className="flex min-w-0 flex-1 overflow-x-auto px-6 py-4"
        style={{ justifyContent: 'safe center' }}
      >
        {isProjectDeployable(project) &&
          project.environments &&
          project.environments.length > 0 && (
            <DeploymentCards
              environments={project.environments}
              releases={project.current_releases ?? {}}
            />
          )}
      </div>
      <div className="flex w-40 shrink-0 justify-center px-6 py-4 whitespace-nowrap">
        <ScoreBadge score={project.score} size="md" variant="circle" />
      </div>
    </div>
  )
})
