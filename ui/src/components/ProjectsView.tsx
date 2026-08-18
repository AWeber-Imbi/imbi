import * as React from 'react'
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  ChevronUp,
  CircleCheck,
  GitCommit,
  GitPullRequest,
  Grid3x3,
  List,
  Plus,
  RefreshCw,
  Search,
  Tag,
  User,
} from 'lucide-react'
import { matchSorter } from 'match-sorter'

import { getProjectsSlim, type ProjectListItem } from '@/api/endpoints'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useSearchShortcut } from '@/hooks/useSearchShortcut'
import { deriveChipColors } from '@/lib/chip-colors'
import { computeDriftPairs, type DriftPair } from '@/lib/deployment-drift'

import { NewProjectDialog } from './NewProjectDialog'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { EnvironmentBadge } from './ui/environment-badge'
import {
  type FilterOption,
  FilterPopover,
  type FilterPopoverProps,
} from './ui/filter-popover'
import { HoverCard, HoverCardContent, HoverCardTrigger } from './ui/hover-card'
import { Input } from './ui/input'
import { Keystroke } from './ui/keystroke'
import { ScoreBadge } from './ui/score-badge'
import { Sk } from './ui/skeleton'

// The dropdown filters, each backed by its own URL search param.
type FacetKey = 'drifts' | 'scores' | 'teams' | 'types'

interface FilterHeaderProps {
  activeFilters: Set<string>
  centerFilter?: FilterPopoverProps & { title: string }
  children: React.ReactNode
  className?: string
  hideMainFilter?: boolean
  label: string
  onSort: () => void
  onToggle: (slug: string) => void
  options: FilterOption[]
  rightFilter?: FilterPopoverProps & { title: string }
  sortDir: SortDir
  sorted: boolean
}

interface ProjectListRowProps {
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

// Footprint skeleton for the projects results area — mirrors the grid cards
// or the table rows depending on the active view, so the layout reads as
// present while the list loads. The filter chrome above renders immediately.
function ProjectsSkeleton({
  count = 9,
  viewMode,
}: {
  count?: number
  viewMode: 'grid' | 'table'
}) {
  if (viewMode === 'grid') {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }).map((_, i) => (
          <Card
            aria-busy
            className="relative flex min-h-56 flex-col p-5"
            key={i}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-2">
                <Sk line w="60%" />
                <Sk line w="40%" />
              </div>
              <Sk circle h={36} w={36} />
            </div>
            <div className="space-y-2">
              <Sk line w="100%" />
              <Sk line w="80%" />
            </div>
            <div className="border-tertiary mt-auto flex items-center gap-2 border-t pt-[18px]">
              <Sk h={20} r={6} w={48} />
              <Sk h={20} r={6} w={48} />
              <Sk className="ml-auto" h={20} r={6} w={72} />
            </div>
          </Card>
        ))}
      </div>
    )
  }
  return (
    <Card aria-busy className="divide-tertiary divide-y overflow-hidden">
      {Array.from({ length: count }).map((_, i) => (
        <div className="flex items-center py-4" key={i}>
          <div className="w-65 shrink-0 space-y-2 px-2.5">
            <Sk line w="70%" />
            <Sk line w="45%" />
          </div>
          <div className="flex w-40 shrink-0 justify-center">
            <Sk h={20} r={6} w={40} />
          </div>
          <div className="flex w-40 shrink-0 justify-center">
            <Sk h={20} r={6} w={56} />
          </div>
          <div className="flex min-w-0 flex-1 justify-center gap-2">
            <Sk h={20} r={6} w={48} />
            <Sk h={20} r={6} w={48} />
          </div>
          <div className="flex w-28 shrink-0 justify-center">
            <Sk circle h={28} w={28} />
          </div>
        </div>
      ))}
    </Card>
  )
}

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
  const { user } = useAuth()
  const orgSlug = selectedOrganization?.slug || ''

  // Team slugs the current user belongs to, scoped to the selected org.
  // Sourced from GET /users/me so the "My Teams" toggle can filter
  // client-side with no extra request, mirroring "My PRs".
  const myTeamSlugs = useMemo(
    () =>
      new Set(
        (user?.teams ?? [])
          .filter((t) => t.organization_slug === orgSlug)
          .map((t) => t.team_slug),
      ),
    [user, orgSlug],
  )

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
  const [searchFocused, setSearchFocused] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)
  useSearchShortcut(searchInputRef)
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
  const scoresParam = searchParams.get('scores') ?? ''
  const hasDrift = searchParams.get('has_drift') === '1'
  const hasOpenPRs = searchParams.get('has_open_prs') === '1'
  const hasMyOpenPRs = searchParams.get('has_my_open_prs') === '1'
  const hasMyTeams = searchParams.get('has_my_teams') === '1'

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
  const toggleMyTeams = toggleBoolParam('has_my_teams')

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

  // One definition of "drifted" for the badge, the ``has_drift``
  // toggle, and the drift facet: a project drifts when it exhibits at
  // least one drift pair.
  const driftedProjectIds = useMemo(() => {
    const ids = new Set<string>()
    for (const p of projects ?? []) {
      if (driftSlugsFor(p).length > 0) ids.add(p.id)
    }
    return ids
  }, [projects])
  const totalDriftProjects = driftedProjectIds.size

  const driftPairOptions = useMemo(() => {
    const seen = new Set<string>()
    for (const p of projects ?? []) {
      for (const slug of driftSlugsFor(p)) seen.add(slug)
    }
    return Array.from(seen)
      .map((slug) => ({ label: driftPairLabel(slug), slug }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [projects])

  const teamSet = useMemo(
    () => new Set(teamsParam.split(',').filter(Boolean)),
    [teamsParam],
  )
  const typeSet = useMemo(
    () => new Set(typesParam.split(',').filter(Boolean)),
    [typesParam],
  )
  const driftSet = useMemo(
    () => new Set(driftsParam.split(',').filter(Boolean)),
    [driftsParam],
  )
  const scoreSet = useMemo(
    () => new Set(scoresParam.split(',').filter(Boolean)),
    [scoresParam],
  )

  // Search runs before the facet filters so both the visible list and
  // the dropdown counts are scoped to the query. matchSorter orders by
  // relevance and ``Array.filter`` is stable, so that order survives.
  const searchedProjects = useMemo(() => {
    const all = projects ?? []
    if (!deferredQuery) return all
    return matchSorter(all, deferredQuery, {
      keys: [
        'name',
        'description',
        'team.name',
        { key: (p) => (p.project_types || []).map((pt) => pt.name) },
      ],
    })
  }, [projects, deferredQuery])

  // Applies every active filter, optionally holding one facet out. The
  // dropdown counts hold their own facet out so that selecting one
  // option doesn't drop its siblings to zero — each count answers "how
  // many projects would this option give me", not "how many match now".
  // fallow-ignore-next-line complexity
  const applyFilters = useCallback(
    (list: ProjectListItem[], skip?: FacetKey) => {
      let all = list
      if (skip !== 'teams' && teamSet.size > 0) {
        all = all.filter((p) => teamSet.has(p.team.slug))
      }
      if (skip !== 'types' && typeSet.size > 0) {
        all = all.filter((p) =>
          (p.project_types ?? []).some((pt) => typeSet.has(pt.slug)),
        )
      }
      if (skip !== 'drifts' && driftSet.size > 0) {
        all = all.filter((p) => driftSlugsFor(p).some((s) => driftSet.has(s)))
      }
      if (hasOpenPRs) {
        all = all.filter((p) => (p.open_pr_count ?? 0) > 0)
      }
      if (hasMyOpenPRs) {
        all = all.filter((p) => (p.viewer_open_pr_count ?? 0) > 0)
      }
      if (hasMyTeams) {
        all = all.filter((p) => myTeamSlugs.has(p.team.slug))
      }
      if (hasDrift) {
        all = all.filter((p) => driftedProjectIds.has(p.id))
      }
      if (skip !== 'scores' && scoreSet.size > 0) {
        all = all.filter((p) => scoreSet.has(scoreBucket(p.score)))
      }
      return all
    },
    [
      teamSet,
      typeSet,
      driftSet,
      scoreSet,
      hasDrift,
      hasOpenPRs,
      hasMyOpenPRs,
      hasMyTeams,
      myTeamSlugs,
      driftedProjectIds,
    ],
  )

  const filteredProjects = useMemo(() => {
    const all = applyFilters(searchedProjects)
    // A query already ordered the list by relevance; don't re-sort it.
    if (deferredQuery) return all
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
  }, [applyFilters, searchedProjects, deferredQuery, sortKey, sortDir])

  // Per-option match totals, one map per facet, keyed by option slug.
  const facetCounts = useMemo(() => {
    const tally = (
      facet: FacetKey,
      slugsFor: (p: ProjectListItem) => string[],
    ) => {
      const counts = new Map<string, number>()
      for (const p of applyFilters(searchedProjects, facet)) {
        for (const slug of slugsFor(p)) {
          counts.set(slug, (counts.get(slug) ?? 0) + 1)
        }
      }
      return counts
    }
    return {
      drifts: tally('drifts', driftSlugsFor),
      scores: tally('scores', (p) => [scoreBucket(p.score)]),
      teams: tally('teams', (p) => [p.team.slug]),
      types: tally('types', (p) =>
        (p.project_types ?? []).map((pt) => pt.slug),
      ),
    }
  }, [applyFilters, searchedProjects])

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
  const totalMyTeamProjects = useMemo(
    () => (projects ?? []).filter((p) => myTeamSlugs.has(p.team.slug)).length,
    [projects, myTeamSlugs],
  )

  const scoreOptions: FilterOption[] = [
    { dotClass: 'bg-success', label: 'Healthy 85–100', slug: 'healthy' },
    { dotClass: 'bg-warning', label: 'Fair 75–84', slug: 'fair' },
    { dotClass: 'bg-danger', label: 'At risk 50–74', slug: 'at-risk' },
    {
      dotClass: 'bg-[var(--color-status-failed-dot)]',
      label: 'Unhealthy < 50',
      slug: 'unhealthy',
    },
    { dotClass: 'bg-muted-foreground', label: 'Unscored', slug: 'unscored' },
  ]
  const teamFilterOptions = withCounts(teamOptions, facetCounts.teams)
  const typeFilterOptions = withCounts(typeOptions, facetCounts.types)
  const driftFilterOptions = withCounts(driftPairOptions, facetCounts.drifts)
  const scoreFilterOptions = withCounts(scoreOptions, facetCounts.scores)

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
                className="pr-8 pl-9"
                disabled={isLoading}
                onBlur={() => setSearchFocused(false)}
                onChange={(e) => setInputQuery(e.target.value)}
                onFocus={() => setSearchFocused(true)}
                placeholder="Search projects..."
                ref={searchInputRef}
                type="text"
                value={inputQuery}
              />
              {!inputQuery && !searchFocused && (
                <div className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2">
                  <Keystroke value="/" />
                </div>
              )}
            </div>

            <div className="flex flex-1 items-center gap-2">
              <StatBadge hidden label="Healthy" value={0} variant="success" />
              <StatBadge hidden label="Deploying" value={0} variant="warning" />
              <StatBadge hidden label="Failed" value={0} variant="danger" />
              <StatBadge
                active={hasDrift}
                disabled={isLoading}
                label="Drifted"
                onClick={toggleDrift}
                value={totalDriftProjects}
                variant="amber"
              />
              <StatBadge
                active={hasOpenPRs}
                disabled={isLoading}
                label="Open PRs"
                onClick={toggleOpenPRs}
                value={totalOpenPRs}
                variant="accent"
              />
              <StatBadge
                active={hasMyOpenPRs}
                disabled={isLoading}
                label="My PRs"
                onClick={toggleMyOpenPRs}
                value={totalMyOpenPRs}
                variant="info"
              />
              <StatBadge
                active={hasMyTeams}
                disabled={isLoading}
                label="My Teams"
                onClick={toggleMyTeams}
                value={totalMyTeamProjects}
                variant="teal"
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
        <ProjectsSkeleton viewMode={viewMode === 'grid' ? 'grid' : 'table'} />
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
                className="relative flex min-h-56 cursor-pointer flex-col p-5 transition-shadow hover:shadow-md"
                key={`card-${project.id}`}
              >
                <Link
                  aria-label={`View ${project.name}`}
                  className="focus-visible:ring-ring absolute inset-0 rounded-lg focus-visible:ring-2 focus-visible:outline-none"
                  to={`/projects/${project.id}`}
                />
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
                    <Link
                      aria-label={`View pull requests for ${project.name}`}
                      className={`border-accent bg-accent text-accent relative z-10 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs ${(project.open_pr_count ?? 0) > 0 ? '' : 'pointer-events-none invisible'}`}
                      to={`/projects/${project.id}/pull-requests`}
                    >
                      <GitPullRequest className="size-3.5" />
                      <span>{project.open_pr_count ?? 0}</span>
                    </Link>
                    <Link
                      aria-label={`View your pull requests for ${project.name}`}
                      className={`border-info bg-info text-info relative z-10 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs ${(project.viewer_open_pr_count ?? 0) > 0 ? '' : 'pointer-events-none invisible'}`}
                      to={`/projects/${project.id}/pull-requests`}
                    >
                      <User className="size-3.5" />
                      <span>{project.viewer_open_pr_count ?? 0}</span>
                    </Link>
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                      <DriftCell inline project={project} />
                    </div>
                    {isProjectDeployable(project) && envs.length > 0 && (
                      <div className="relative z-10 ml-auto flex flex-wrap items-center gap-2">
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
              activeFilters={teamSet}
              centerFilter={{
                activeFilters: teamSet,
                label: 'team',
                onToggle: (s) => toggleFilter('teams', s),
                options: teamFilterOptions,
                title: 'Team',
              }}
              className="w-65 shrink-0"
              hideMainFilter
              label="team"
              onSort={() => setSort('name')}
              onToggle={(s) => toggleFilter('teams', s)}
              options={teamFilterOptions}
              rightFilter={{
                activeFilters: typeSet,
                label: 'type',
                onToggle: (s) => toggleFilter('types', s),
                options: typeFilterOptions,
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
                  activeFilters={driftSet}
                  label="drift"
                  onToggle={(s) => toggleFilter('drifts', s)}
                  options={driftFilterOptions}
                />
              </div>
            </div>
            <div className="min-w-0 flex-1 px-6 py-3 text-center whitespace-nowrap">
              Current Deployments &amp; Releases
            </div>
            <div
              className="hover:text-primary w-28 shrink-0 cursor-pointer px-6 py-3 text-center whitespace-nowrap select-none"
              onClick={() => setSort('score')}
            >
              <span className="inline-flex items-center gap-1">
                Score
                {sortKey === 'score' ? (
                  sortDir === 'asc' ? (
                    <ChevronUp className="size-3.5 shrink-0" />
                  ) : (
                    <ChevronDown className="size-3.5 shrink-0" />
                  )
                ) : (
                  <ChevronsUpDown className="text-tertiary/50 size-3.5 shrink-0" />
                )}
                <span onClick={(e) => e.stopPropagation()}>
                  <FilterPopover
                    activeFilters={scoreSet}
                    label="health score"
                    onToggle={(s) => toggleFilter('scores', s)}
                    options={scoreFilterOptions}
                  />
                </span>
              </span>
            </div>
          </div>
          <div
            className="divide-tertiary divide-y overflow-y-auto"
            style={{
              maxHeight: 'calc(100vh - 330px - var(--assistant-height, 64px))',
            }}
          >
            {filteredProjects.map((project) => (
              <ProjectListRow key={`row-${project.id}`} project={project} />
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

// Resolve a release's ``performed_by`` to an email when possible so the
// attribution chip renders a consistent display name + Gravatar:
// ``performed_by`` may be a raw remote login, an email, or an already
// resolved display name. Emails pass through; a bare login is mapped to
// the matching Imbi user's email via the local-part lookup; anything
// unmatched returns ``undefined`` so the caller falls back to the actor
// string verbatim.
export function resolveActorEmail(
  actor: null | string | undefined,
  loginToEmail: Map<string, string>,
): string | undefined {
  if (!actor) return undefined
  if (actor.includes('@')) return actor
  return loginToEmail.get(actor)
}

function abbreviateEnvName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return ''
  if (parts.length === 1) return parts[0][0]!.toUpperCase()
  return parts.map((w) => w[0]!.toUpperCase()).join('')
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
              <ReleaseStamp release={release} />
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
    id: string
    project_types?: null | object[]
    release_summary?: null | {
      commits_since_tag: number
      head_sha: null | string
    }
  }
}) {
  const { isDarkMode } = useTheme()
  // z-10 lifts the badges above the row/card overlay Link so their own
  // deep-links win the click.
  const containerCls = inline
    ? 'relative z-10 flex flex-row flex-wrap items-center gap-1'
    : 'relative z-10 flex flex-col items-center gap-1.5'
  const badgeBaseCls = inline
    ? 'inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-mono text-xs'
    : 'inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-xs'
  const fallbackCls = 'border-amber-border bg-amber-bg text-amber-text border'

  const deployDrifted: DriftPair[] = isProjectDeployable(project)
    ? computeDriftPairs(
        project.environments ?? [],
        project.current_releases ?? {},
      ).filter((p) => p.drifted)
    : []

  const releaseDrifted =
    isProjectReleasable(project) && projectReleaseDrifted(project)

  if (deployDrifted.length === 0 && !releaseDrifted) return null

  return (
    <div className={containerCls}>
      {deployDrifted.map((p) => {
        const derived = p.toLabelColor
          ? deriveChipColors(p.toLabelColor, isDarkMode)
          : null
        return (
          <Link
            aria-label={`Deploy ${p.from} to ${p.to}`}
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
            to={`/projects/${project.id}/deployments?env=${encodeURIComponent(p.toSlug)}`}
          >
            <span className="font-medium">Δ</span>
            <span>{abbreviateEnvName(p.from)}</span>
            <span>→</span>
            <span>{abbreviateEnvName(p.to)}</span>
          </Link>
        )
      })}
      {releaseDrifted && (
        <Link
          aria-label="Cut a release"
          className={`${badgeBaseCls} ${fallbackCls}`}
          to={`/projects/${project.id}/releases`}
        >
          <span className="font-medium">Δ</span>
          <span>C</span>
          <span>→</span>
          <span>R</span>
        </Link>
      )}
    </div>
  )
}

// Human-readable name for a slug produced by ``driftSlugsFor``.
function driftPairLabel(slug: string): string {
  if (slug === 'C->R') return 'C → R (commit → release)'
  const [from, to] = slug.split('->')
  return `${abbreviateEnvName(from)} → ${abbreviateEnvName(to)}`
}

// Every drift-pair slug a project currently exhibits: ``from->to`` for
// each drifted adjacent environment pair, plus the pseudo-pair ``C->R``
// when a releasable project has commits past its latest tag. Backs both
// the drift filter and the per-option counts in its popover.
function driftSlugsFor(project: ProjectListItem): string[] {
  const slugs: string[] = []
  if (isProjectDeployable(project)) {
    const pairs = computeDriftPairs(
      project.environments ?? [],
      project.current_releases ?? {},
    )
    for (const pair of pairs) {
      if (pair.drifted) slugs.push(`${pair.from}->${pair.to}`)
    }
  }
  if (isProjectReleasable(project) && projectReleaseDrifted(project)) {
    slugs.push('C->R')
  }
  return slugs
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
          <ReleaseStamp release={release} />
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

function isProjectDeployable(project: {
  project_types?: null | object[]
}): boolean {
  return (project.project_types ?? []).some(
    (pt) => (pt as { deployable?: boolean }).deployable === true,
  )
}

function isProjectReleasable(project: {
  project_types?: null | object[]
}): boolean {
  return (project.project_types ?? []).some(
    (pt) => (pt as { releasable?: boolean }).releasable === true,
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

function projectReleaseDrifted(project: {
  release_summary?: null | {
    commits_since_tag: number
    head_sha: null | string
  }
}): boolean {
  const s = project.release_summary
  if (!s?.head_sha) return false
  return s.commits_since_tag > 0
}

function ReleaseCards({
  release_summary,
}: {
  release_summary: {
    head_authored_at: null | string
    head_sha: null | string
    head_short_sha: null | string
    latest_tag: null | string
    latest_tag_at: null | string
    latest_tag_sha: null | string
  }
}) {
  const headSha =
    release_summary.head_short_sha ??
    release_summary.head_sha?.slice(0, 7) ??
    null
  return (
    <div className="flex items-start gap-2" style={{ flexWrap: 'nowrap' }}>
      <span className="border-border bg-card w-50 rounded-lg border px-3 py-2">
        <p className="text-secondary mb-1.5 flex items-center gap-1.5 text-sm font-medium">
          <GitCommit className="size-3 shrink-0" />
          Latest Commit
        </p>
        <p className="flex items-center gap-2 font-mono text-base leading-tight">
          <span className="text-primary">{headSha ?? '—'}</span>
        </p>
        <p className="text-tertiary mt-1 flex items-center text-xs">
          {release_summary.head_authored_at && (
            <RelativeTime value={release_summary.head_authored_at} />
          )}
        </p>
      </span>
      <ArrowRight className="text-tertiary mx-2 mt-3 size-3.5 shrink-0 self-start" />
      <span className="border-amber-border bg-amber-bg w-50 rounded-lg border px-3 py-2">
        <p className="text-amber-text mb-1.5 flex items-center gap-1.5 text-sm font-medium">
          <Tag className="size-3 shrink-0" />
          Current Release
        </p>
        <p className="flex items-center gap-2 font-mono text-base leading-tight">
          <span className="text-primary">
            {release_summary.latest_tag ?? '—'}
          </span>
          {release_summary.latest_tag_sha && (
            <span className="text-tertiary text-xs font-normal">
              {release_summary.latest_tag_sha.slice(0, 7)}
            </span>
          )}
        </p>
        <p className="text-tertiary mt-1 flex items-center text-xs">
          {release_summary.latest_tag_at && (
            <RelativeTime value={release_summary.latest_tag_at} />
          )}
        </p>
      </span>
    </div>
  )
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

// Deployment timestamp footer shared by the grid card and the hover card.
function ReleaseStamp({
  release,
}: {
  release?: null | { deployed_at: string }
}) {
  return (
    <p className="text-tertiary mt-1 flex items-center text-xs">
      {release ? (
        <RelativeTime value={release.deployed_at} />
      ) : (
        <span className="invisible">—</span>
      )}
    </p>
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

// Health-score bucket slug, matching the ``scoreOptions`` slugs.
function scoreBucket(score: null | number | undefined): string {
  if (score == null) return 'unscored'
  if (score >= 85) return 'healthy'
  if (score >= 75) return 'fair'
  if (score >= 50) return 'at-risk'
  return 'unhealthy'
}

function ScrollableDeployments({
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const checkScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 0)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    checkScroll()
    el.addEventListener('scroll', checkScroll)
    const ro = new ResizeObserver(checkScroll)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', checkScroll)
      ro.disconnect()
    }
  }, [environments])

  const scroll = (dir: 'left' | 'right') => {
    const el = scrollRef.current
    if (!el) return
    el.scrollBy({ behavior: 'smooth', left: dir === 'left' ? -200 : 200 })
  }

  return (
    <div className="relative flex min-w-0 items-center">
      {canScrollLeft && (
        <button
          className="from-card/90 text-secondary hover:text-primary absolute left-0 z-10 flex h-full items-center bg-linear-to-r to-transparent pr-3 pl-0.5"
          onClick={() => scroll('left')}
          type="button"
        >
          <ChevronLeft className="size-4" />
        </button>
      )}
      <div
        className="overflow-x-auto"
        ref={scrollRef}
        style={{ scrollbarWidth: 'none' }}
      >
        <DeploymentCards environments={environments} releases={releases} />
      </div>
      {canScrollRight && (
        <button
          className="from-card/90 text-secondary hover:text-primary absolute right-0 z-10 flex h-full items-center bg-linear-to-l to-transparent pr-0.5 pl-3"
          onClick={() => scroll('right')}
          type="button"
        >
          <ChevronRight className="size-4" />
        </button>
      )}
    </div>
  )
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

// Attaches each option's match total; slugs missing from the tally have
// no matching projects left under the other active filters.
function withCounts(
  options: FilterOption[],
  counts: Map<string, number>,
): FilterOption[] {
  return options.map((opt) => ({ ...opt, count: counts.get(opt.slug) ?? 0 }))
}

// Memoized list-mode row so a parent re-render (e.g. an ``inputQuery``
// keystroke) doesn't redo the JSX for every row in the table. The
// ``project`` reference comes from a memoized filter pipeline, so as
// long as the underlying object identity is stable (it is — React Query
// returns the same array between renders), the row skips its render.
// fallow-ignore-next-line complexity
const ProjectListRow = React.memo(function ProjectListRow({
  project,
}: ProjectListRowProps) {
  return (
    <div className="hover:bg-secondary relative flex cursor-pointer items-center transition-colors">
      <Link
        aria-label={`View ${project.name}`}
        className="focus-visible:ring-ring absolute inset-0 focus-visible:ring-2 focus-visible:outline-none"
        to={`/projects/${project.id}`}
      />
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
            <Link
              aria-label={`View pull requests for ${project.name}`}
              className="border-accent bg-accent text-accent relative z-10 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs"
              to={`/projects/${project.id}/pull-requests`}
            >
              <GitPullRequest className="size-3.5" />
              <span>{project.open_pr_count}</span>
            </Link>
          )}
          {(project.viewer_open_pr_count ?? 0) > 0 && (
            <Link
              aria-label={`View your pull requests for ${project.name}`}
              className="border-info bg-info text-info relative z-10 inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs"
              to={`/projects/${project.id}/pull-requests`}
            >
              <User className="size-3.5" />
              <span>{project.viewer_open_pr_count}</span>
            </Link>
          )}
        </div>
      </div>
      <div className="flex w-40 shrink-0 items-center justify-center px-5 py-4">
        <DriftCell project={project} />
      </div>
      <div
        className="flex min-w-0 flex-1 px-6 py-4"
        style={{ justifyContent: 'safe center' }}
      >
        {isProjectDeployable(project) &&
          project.environments &&
          project.environments.length > 0 && (
            <ScrollableDeployments
              environments={project.environments}
              releases={project.current_releases ?? {}}
            />
          )}
        {!isProjectDeployable(project) &&
          isProjectReleasable(project) &&
          project.release_summary && (
            <div className="min-w-0 overflow-x-auto">
              <ReleaseCards release_summary={project.release_summary} />
            </div>
          )}
      </div>
      <div className="flex w-28 shrink-0 justify-center px-6 py-4 whitespace-nowrap">
        <ScoreBadge score={project.score} size="md" variant="circle" />
      </div>
    </div>
  )
})
