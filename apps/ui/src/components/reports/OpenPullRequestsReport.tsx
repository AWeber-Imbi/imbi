import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink, GitPullRequest, RefreshCw } from 'lucide-react'

import { getOrgPullRequests, type ProjectListItem } from '@/api/endpoints'
import { DiffBar } from '@/components/pull-requests/DiffBar'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { UserIdentity } from '@/components/ui/user-identity'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useLoginToEmail } from '@/hooks/useLoginToEmail'
import { useProjectsSlimMap } from '@/hooks/useProjectsSlimMap'
import { relTime } from '@/lib/formatDate'
import type { PullRequest } from '@/types'

interface AuthorInfo {
  actor: string | undefined
  displayNamesForUser: Map<string, string> | undefined
  emailOrAuthor: string
  linkToProfile: boolean
  tooltip: string
}

interface EnrichedPR extends PullRequest {
  project_name: string
  project_slug: string
  project_types: { name: string; slug: string }[]
  team_name: string
  team_slug: string
}

interface ReportData {
  enriched: EnrichedPR[]
  hasError: boolean
  isLoading: boolean
  projectTypeOptions: SlugName[]
  refreshAll: () => void
  teamOptions: SlugName[]
}

interface ReportFilters {
  projectTypeFilter: string
  search: string
  setProjectTypeFilter: (v: string) => void
  setSearch: (v: string) => void
  setTeamFilter: (v: string) => void
  teamFilter: string
}

interface SlugName {
  name: string
  slug: string
}

const ALL = '__all__'

const COLUMN_ALIGN: Record<'center' | 'left' | 'right', string> = {
  center: 'text-center',
  left: 'text-left',
  right: 'text-right',
}

const COLUMNS: {
  align: 'center' | 'left' | 'right'
  label: string
  width?: string
}[] = [
  { align: 'left', label: 'Team', width: 'w-20' },
  { align: 'left', label: 'Project Type', width: 'w-32' },
  { align: 'left', label: 'Project', width: 'w-44' },
  { align: 'left', label: '#', width: 'w-16' },
  { align: 'left', label: 'Title' },
  { align: 'center', label: 'Author', width: 'w-10' },
  { align: 'center', label: 'Files', width: 'w-14' },
  { align: 'center', label: 'Diff', width: 'w-36' },
  { align: 'right', label: 'Updated', width: 'w-20' },
]

export function OpenPullRequestsReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const navigate = useNavigate()

  const filters = useReportFilters()
  const data = useOpenPrReportData(orgSlug)
  const { displayNames, loginToEmail } = useLoginToEmail()
  const filtered = useOpenPrFilters(
    data.enriched,
    filters.teamFilter,
    filters.projectTypeFilter,
    filters.search,
  )

  return (
    <TooltipProvider delayDuration={200}>
      <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
        <ReportToolbar
          data={data}
          filteredCount={filtered.length}
          filters={filters}
        />
        <ReportTable
          data={data}
          displayNames={displayNames}
          filtered={filtered}
          loginToEmail={loginToEmail}
          onOpenProject={(id) => navigate(`/projects/${id}`)}
        />
      </div>
    </TooltipProvider>
  )
}

function bodyStatus({
  filtered,
  hasError,
  showSkeleton,
}: {
  filtered: EnrichedPR[]
  hasError: boolean
  showSkeleton: boolean
}): 'empty' | 'error' | 'loading' | 'ready' {
  if (hasError) return 'error'
  if (showSkeleton) return 'loading'
  if (filtered.length === 0) return 'empty'
  return 'ready'
}

function deriveSlugNameOptions(
  rows: EnrichedPR[],
  getPairs: (pr: EnrichedPR) => readonly (readonly [string, string])[],
): SlugName[] {
  const map = new Map<string, string>()
  for (const pr of rows) {
    for (const [slug, name] of getPairs(pr)) map.set(slug, name)
  }
  return [...map.entries()]
    .map(([slug, name]) => ({ name, slug }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

function EmptyRow() {
  return (
    <tr>
      <td className="text-tertiary px-4 py-12 text-center" colSpan={9}>
        No open pull requests match the current filters.
      </td>
    </tr>
  )
}

function enrichPullRequests(
  prs: PullRequest[],
  projectsById: Map<string, ProjectListItem>,
): EnrichedPR[] {
  const out: EnrichedPR[] = []
  for (const pr of prs) {
    const p = projectsById.get(pr.project_id)
    if (!p || !includePr(pr, p)) continue
    out.push({
      ...pr,
      project_name: p.name,
      project_slug: p.slug,
      project_types: p.project_types,
      team_name: p.team.name,
      team_slug: p.team.slug,
    })
  }
  out.sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )
  return out
}

function ErrorRow({ onRetry }: { onRetry: () => void }) {
  return (
    <tr>
      <td className="px-4 py-8 text-center" colSpan={9}>
        <div className="text-danger text-sm">Failed to load pull requests.</div>
        <button
          className="text-action mt-2 text-xs hover:underline"
          onClick={onRetry}
          type="button"
        >
          Retry
        </button>
      </td>
    </tr>
  )
}

function FilterSelect({
  label,
  onValueChange,
  options,
  placeholder,
  value,
}: {
  label: string
  onValueChange: (v: string) => void
  options: SlugName[]
  placeholder: string
  value: string
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-tertiary text-xs">{label}</label>
      <Select onValueChange={onValueChange} value={value}>
        <SelectTrigger className="h-8 w-44 text-xs">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{placeholder}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.slug} value={o.slug}>
              {o.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function includePr(pr: PullRequest, p: ProjectListItem): boolean {
  if (pr.draft) return false
  if (pr.state !== 'open') return false
  if (p.archived) return false
  return true
}

function matchesSearch(r: EnrichedPR, q: string): boolean {
  return (
    r.title.toLowerCase().includes(q) ||
    r.author.toLowerCase().includes(q) ||
    r.project_name.toLowerCase().includes(q) ||
    String(r.pr_number).includes(q)
  )
}

function PrAuthorCell({ info }: { info: AuthorInfo }) {
  return (
    <td className="px-4 py-3">
      <div className="flex justify-center">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <UserIdentity
                actor={info.actor}
                displayNames={info.displayNamesForUser}
                email={info.actor ? undefined : info.emailOrAuthor}
                hideName
                linkToProfile={info.linkToProfile}
                size="small"
                title=""
              />
            </span>
          </TooltipTrigger>
          <TooltipContent>{info.tooltip}</TooltipContent>
        </Tooltip>
      </div>
    </td>
  )
}

function PrNumberCell({ number }: { number: number }) {
  return (
    <td className="px-4 py-3">
      <span className="text-tertiary flex items-center gap-1.5 text-xs">
        <GitPullRequest className="text-success size-3.5 shrink-0" />
        {number}
      </span>
    </td>
  )
}

function PrProjectCell({ name, onOpen }: { name: string; onOpen: () => void }) {
  return (
    <td className="max-w-44 px-4 py-3">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            className="text-primary hover:text-action block w-full truncate text-left text-sm font-medium transition-colors"
            onClick={onOpen}
            type="button"
          >
            {name}
          </button>
        </TooltipTrigger>
        <TooltipContent>{name}</TooltipContent>
      </Tooltip>
    </td>
  )
}

function PrProjectTypesCell({
  types,
}: {
  types: { name: string; slug: string }[]
}) {
  return (
    <td className="px-4 py-3">
      <div className="flex flex-wrap gap-1">
        {types.map((pt) => (
          <Badge key={pt.slug} variant="neutral">
            {pt.slug}
          </Badge>
        ))}
      </div>
    </td>
  )
}

function PrRow({
  displayNames,
  loginToEmail,
  onOpenProject,
  pr,
}: {
  displayNames: Map<string, string>
  loginToEmail: Map<string, string>
  onOpenProject: () => void
  pr: EnrichedPR
}) {
  const authorInfo = resolveAuthorInfo(pr.author, loginToEmail, displayNames)
  return (
    <tr className="border-tertiary hover:bg-secondary/30 border-b transition-colors last:border-b-0">
      <td className="text-secondary px-4 py-3 font-mono text-xs">
        {pr.team_slug}
      </td>
      <PrProjectTypesCell types={pr.project_types} />
      <PrProjectCell name={pr.project_name} onOpen={onOpenProject} />
      <PrNumberCell number={pr.pr_number} />
      <PrTitleCell title={pr.title} url={pr.url} />
      <PrAuthorCell info={authorInfo} />
      <td className="text-secondary px-4 py-3 text-center">
        {pr.changed_files}
      </td>
      <td className="px-4 py-3 text-center">
        <DiffBar additions={pr.additions} deletions={pr.deletions} />
      </td>
      <td className="text-tertiary px-4 py-3 text-right text-xs tabular-nums">
        {relTime(pr.updated_at)}
      </td>
    </tr>
  )
}

function PrRows({
  displayNames,
  filtered,
  loginToEmail,
  onOpenProject,
}: {
  displayNames: Map<string, string>
  filtered: EnrichedPR[]
  loginToEmail: Map<string, string>
  onOpenProject: (id: string) => void
}) {
  return (
    <>
      {filtered.map((pr) => (
        <PrRow
          displayNames={displayNames}
          key={pr.pr_id}
          loginToEmail={loginToEmail}
          onOpenProject={() => onOpenProject(pr.project_id)}
          pr={pr}
        />
      ))}
    </>
  )
}

function PrTitleCell({ title, url }: { title: string; url: string }) {
  return (
    <td className="max-w-0 px-4 py-3">
      <Tooltip>
        <TooltipTrigger asChild>
          <a
            className="text-primary hover:text-action inline-flex max-w-full items-center gap-1.5 transition-colors"
            href={url}
            rel="noreferrer"
            target="_blank"
          >
            <span className="truncate">{title}</span>
            <ExternalLink className="text-tertiary size-3 shrink-0" />
          </a>
        </TooltipTrigger>
        <TooltipContent>{title}</TooltipContent>
      </Tooltip>
    </td>
  )
}

function ReportTable({
  data,
  displayNames,
  filtered,
  loginToEmail,
  onOpenProject,
}: {
  data: ReportData
  displayNames: Map<string, string>
  filtered: EnrichedPR[]
  loginToEmail: Map<string, string>
  onOpenProject: (id: string) => void
}) {
  const showSkeleton = data.isLoading && data.enriched.length === 0
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <ReportTableHead />
        <tbody>
          <ReportTableBody
            displayNames={displayNames}
            filtered={filtered}
            hasError={data.hasError}
            loginToEmail={loginToEmail}
            onOpenProject={onOpenProject}
            onRetry={data.refreshAll}
            showSkeleton={showSkeleton}
          />
        </tbody>
      </table>
    </div>
  )
}

function ReportTableBody({
  displayNames,
  filtered,
  hasError,
  loginToEmail,
  onOpenProject,
  onRetry,
  showSkeleton,
}: {
  displayNames: Map<string, string>
  filtered: EnrichedPR[]
  hasError: boolean
  loginToEmail: Map<string, string>
  onOpenProject: (id: string) => void
  onRetry: () => void
  showSkeleton: boolean
}) {
  const status = bodyStatus({ filtered, hasError, showSkeleton })
  if (status === 'error') return <ErrorRow onRetry={onRetry} />
  if (status === 'loading') return <SkeletonRows />
  if (status === 'empty') return <EmptyRow />
  return (
    <PrRows
      displayNames={displayNames}
      filtered={filtered}
      loginToEmail={loginToEmail}
      onOpenProject={onOpenProject}
    />
  )
}

function ReportTableHead() {
  return (
    <thead>
      <tr className="border-tertiary border-b">
        {COLUMNS.map((c) => (
          <th
            className={`text-tertiary px-4 py-2 text-xs font-medium tracking-wide uppercase ${COLUMN_ALIGN[c.align]} ${c.width ?? ''}`}
            key={c.label}
          >
            {c.label}
          </th>
        ))}
      </tr>
    </thead>
  )
}

function ReportToolbar({
  data,
  filteredCount,
  filters,
}: {
  data: ReportData
  filteredCount: number
  filters: ReportFilters
}) {
  return (
    <div className="border-tertiary flex flex-wrap items-center gap-3 border-b px-4 py-3">
      <FilterSelect
        label="Team"
        onValueChange={filters.setTeamFilter}
        options={data.teamOptions}
        placeholder="All teams"
        value={filters.teamFilter}
      />
      <FilterSelect
        label="Project type"
        onValueChange={filters.setProjectTypeFilter}
        options={data.projectTypeOptions}
        placeholder="All types"
        value={filters.projectTypeFilter}
      />
      <div className="flex flex-1 items-center justify-end gap-2">
        <input
          className="border-input bg-background text-primary focus:ring-action h-8 w-64 rounded border px-3 text-sm focus:ring-1 focus:outline-none"
          onChange={(e) => filters.setSearch(e.target.value)}
          placeholder="Filter by title, author, project, or #"
          type="text"
          value={filters.search}
        />
        <span className="text-tertiary text-xs">
          {filteredCount} of {data.enriched.length}
        </span>
        <button
          aria-label="Refresh"
          className="text-tertiary hover:text-primary rounded p-1.5 transition-colors"
          disabled={data.isLoading}
          onClick={data.refreshAll}
          type="button"
        >
          <RefreshCw
            className={`size-4 ${data.isLoading ? 'animate-spin' : ''}`}
          />
        </button>
      </div>
    </div>
  )
}

function resolveAuthorInfo(
  author: string,
  loginToEmail: Map<string, string>,
  displayNames: Map<string, string>,
): AuthorInfo {
  const email = loginToEmail.get(author)
  if (!email) {
    return {
      actor: author,
      displayNamesForUser: undefined,
      emailOrAuthor: author,
      linkToProfile: false,
      tooltip: author,
    }
  }
  return {
    actor: undefined,
    displayNamesForUser: displayNames,
    emailOrAuthor: email,
    linkToProfile: true,
    tooltip: displayNames.get(email) ?? author,
  }
}

function SkeletonRow() {
  return (
    <tr className="border-tertiary border-b">
      <td className="px-4 py-3">
        <Sk line w={48} />
      </td>
      <td className="px-4 py-3">
        <Sk h={18} r={4} w={56} />
      </td>
      <td className="px-4 py-3">
        <Sk line w={120} />
      </td>
      <td className="px-4 py-3">
        <Sk line w={32} />
      </td>
      <td className="px-4 py-3">
        <Sk line w="80%" />
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-center">
          <Sk circle h={24} w={24} />
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-center">
          <Sk line w={20} />
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-center">
          <Sk h={10} r={4} w={120} />
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end">
          <Sk line w={48} />
        </div>
      </td>
    </tr>
  )
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 6 }).map((_, i) => (
        <SkeletonRow key={i} />
      ))}
    </>
  )
}

function useOpenPrFilters(
  enriched: EnrichedPR[],
  teamFilter: string,
  projectTypeFilter: string,
  search: string,
): EnrichedPR[] {
  return useMemo(() => {
    let rows = enriched
    if (teamFilter !== ALL) {
      rows = rows.filter((r) => r.team_slug === teamFilter)
    }
    if (projectTypeFilter !== ALL) {
      rows = rows.filter((r) =>
        r.project_types.some((pt) => pt.slug === projectTypeFilter),
      )
    }
    const q = search.trim().toLowerCase()
    if (q) rows = rows.filter((r) => matchesSearch(r, q))
    return rows
  }, [enriched, teamFilter, projectTypeFilter, search])
}

function useOpenPrReportData(orgSlug: string) {
  const {
    data: prData,
    isError: prsError,
    isFetching: prsFetching,
    refetch: refetchPrs,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgPullRequests(orgSlug, { limit: 500, state: 'open' }, signal),
    queryKey: ['org-prs', orgSlug, 'open'],
    staleTime: 60_000,
  })

  const {
    isError: projectsError,
    isFetching: projectsFetching,
    projectsById,
    refetch: refetchProjects,
  } = useProjectsSlimMap(orgSlug)

  const enriched = useMemo(
    () => enrichPullRequests(prData?.data ?? [], projectsById),
    [prData, projectsById],
  )

  const { projectTypeOptions, teamOptions } = useReportOptions(enriched)

  function refreshAll() {
    void refetchPrs()
    void refetchProjects()
  }

  return {
    enriched,
    hasError: prsError || projectsError,
    isLoading: prsFetching || projectsFetching,
    projectTypeOptions,
    refreshAll,
    teamOptions,
  }
}

function useReportFilters(): ReportFilters {
  const [teamFilter, setTeamFilter] = useState<string>(ALL)
  const [projectTypeFilter, setProjectTypeFilter] = useState<string>(ALL)
  const [search, setSearch] = useState('')
  return {
    projectTypeFilter,
    search,
    setProjectTypeFilter,
    setSearch,
    setTeamFilter,
    teamFilter,
  }
}

function useReportOptions(enriched: EnrichedPR[]) {
  const teamOptions = useMemo(
    () =>
      deriveSlugNameOptions(enriched, (pr) => [[pr.team_slug, pr.team_name]]),
    [enriched],
  )
  const projectTypeOptions = useMemo(
    () =>
      deriveSlugNameOptions(enriched, (pr) =>
        pr.project_types.map((pt) => [pt.slug, pt.name] as const),
      ),
    [enriched],
  )
  return { projectTypeOptions, teamOptions }
}
