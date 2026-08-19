import { useEffect, useMemo, useState } from 'react'

import { Link, useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  Loader2,
  Package,
  Plus,
  Search,
  SquarePen,
} from 'lucide-react'

import { getComponentUsage, searchComponents } from '@/api/endpoints'
import { AddAdvisoryDialog } from '@/components/packages/AddAdvisoryDialog'
import { AdvisoryChips } from '@/components/packages/AdvisoryChips'
import { ComponentNotesDialog } from '@/components/packages/ComponentNotesDialog'
import { ComponentStatusMenu } from '@/components/packages/ComponentStatusMenu'
import { EnvironmentChips } from '@/components/packages/EnvironmentChips'
import { useComponentGovernance } from '@/components/packages/useComponentGovernance'
import { FilterPopover } from '@/components/ui/filter-popover'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useExpandedKeys } from '@/hooks/useExpandedKeys'
import { queryKeys } from '@/lib/queryKeys'
import type {
  ComponentSearchResult,
  ComponentUsage,
  ComponentUsageVersion,
} from '@/types'

import {
  EMPTY_FACETS,
  facetsAreEmpty,
  filterUsageVersions,
  type UsageFacetKey,
  usageFacetOptions,
  type UsageFacets,
  usageRows,
} from './package-usage'

/** localStorage key for the recently-viewed package list. */
const RECENT_KEY = 'imbi.packageUsage.recent'
const RECENT_LIMIT = 8

const FACET_LABEL: Record<UsageFacetKey, string> = {
  environment: 'Environment',
  project_type: 'Project type',
  team: 'Team',
}

const FACET_KEYS: UsageFacetKey[] = ['project_type', 'team', 'environment']

interface RecentPackage {
  ecosystem?: string
  id: string
  purl_name: string
}

export function PackageUsageReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const { user } = useAuth()
  const canWrite =
    user?.is_admin === true ||
    (user?.permissions ?? []).includes('component:write')

  const [params, setParams] = useSearchParams()
  const componentId = params.get('component') ?? ''
  const [search, setSearch] = useState('')
  // What was submitted, not what is being typed. A keystroke-driven
  // search bills a full catalog match per character and lands most of
  // its answers in the bin — the reader is typing toward a name they
  // already know, so the useful query is the one they finish.
  const [submitted, setSubmitted] = useState('')
  const [recent, setRecent] = useState<RecentPackage[]>(readRecent)
  const [ecosystems, setEcosystems] = useState<Set<string>>(new Set())
  const [facets, setFacets] = useState<UsageFacets>(EMPTY_FACETS)

  const query = submitted
  // One selected ecosystem narrows the search server-side, which is
  // the case worth a round trip: the reader picked "npm" to stop
  // seeing pypi. Several selected is a client-side trim of the page
  // that came back — the endpoint takes one ecosystem, and widening it
  // to a list to serve a rare selection is not worth the query.
  const serverEcosystem = ecosystems.size === 1 ? [...ecosystems][0] : ''

  const results = useQuery({
    enabled: !!orgSlug && !!query,
    queryFn: ({ signal }) =>
      searchComponents(
        orgSlug,
        { ecosystem: serverEcosystem, limit: 25, q: query },
        signal,
      ),
    queryKey: queryKeys.componentSearch(orgSlug, query, serverEcosystem),
  })

  // The catalog line's counts, and the package-type facet's options.
  // An empty `q` returns totals and no rows, so this is the cheap
  // request — it never walks the catalog to build a list the screen
  // then throws away.
  const catalog = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => searchComponents(orgSlug, { limit: 1 }, signal),
    queryKey: queryKeys.componentSearch(orgSlug, '', ''),
  })

  const usage = useQuery({
    enabled: !!orgSlug && !!componentId,
    queryFn: ({ signal }) => getComponentUsage(orgSlug, componentId, signal),
    queryKey: queryKeys.componentUsage(orgSlug, componentId),
  })

  // Remember what was opened, not what was searched for: the dropdown's
  // value to a returning reader is "the package I was just looking at".
  useEffect(() => {
    const pkg = usage.data
    if (!pkg) return
    setRecent((prev) => {
      const next = [
        { ecosystem: pkg.ecosystem, id: pkg.id, purl_name: pkg.purl_name },
        ...prev.filter((entry) => entry.id !== pkg.id),
      ].slice(0, RECENT_LIMIT)
      writeRecent(next)
      return next
    })
  }, [usage.data])

  // Selecting keeps the term that found the package. Clearing it
  // would flip the still-open dropdown back to the recents list,
  // which reads as the search having been thrown away.
  const select = (id: string) => setParams(id ? { component: id } : {})

  const runSearch = (next: string) => {
    setSubmitted(next)
    // A new search retires the package on screen. Leaving the previous
    // package's table up while a different query runs reads as that
    // query's answer, and the search is slow enough for someone to act
    // on the wrong table before it is replaced.
    if (next) setParams({})
  }

  const rows = useMemo(
    () => (usage.data ? usageRows(usage.data) : []),
    [usage.data],
  )
  const reset = () => {
    setEcosystems(new Set())
    setFacets(EMPTY_FACETS)
  }
  const toggleFacet = (key: UsageFacetKey, slug: string) =>
    setFacets((prev) => ({ ...prev, [key]: toggled(prev[key], slug) }))

  const totals = catalog.data?.ecosystem_totals ?? {}
  const hits = (results.data?.data ?? []).filter(
    (hit) => ecosystems.size < 2 || ecosystems.has(hit.ecosystem),
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterPopover
          activeFilters={ecosystems}
          label="Package type"
          onClear={() => setEcosystems(new Set())}
          onToggle={(slug) => setEcosystems((prev) => toggled(prev, slug))}
          options={Object.entries(totals)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([name, count]) => ({ count, label: name, slug: name }))}
          variant="button"
        />
        {FACET_KEYS.map((key) => (
          <FilterPopover
            activeFilters={facets[key]}
            key={key}
            label={FACET_LABEL[key]}
            onClear={() =>
              setFacets((prev) => ({ ...prev, [key]: new Set<string>() }))
            }
            onToggle={(slug) => toggleFacet(key, slug)}
            options={usageFacetOptions(rows, facets, key)}
            variant="button"
          />
        ))}
        <button
          className="text-secondary hover:bg-secondary hover:text-primary h-8 rounded-lg px-3 text-xs"
          onClick={reset}
          type="button"
        >
          Reset
        </button>
        <div className="text-tertiary ml-auto text-xs">
          <CatalogSummary
            ecosystems={ecosystems}
            facets={facets}
            totals={totals}
          />
        </div>
      </div>

      <PackageSearch
        hits={hits}
        isSearching={results.isFetching}
        onSearch={runSearch}
        onSelect={select}
        query={query}
        recent={recent}
        search={search}
        setSearch={setSearch}
        total={results.data?.total ?? 0}
      />

      {!componentId && <EmptyPrompt />}
      {componentId && usage.isLoading && <UsageSkeleton />}
      {componentId && usage.isError && (
        <p className="text-danger text-sm">Could not load this package.</p>
      )}
      {componentId && usage.data && (
        // Keyed by package so switching packages remounts the detail —
        // expanded version rows and any open dialog belong to the
        // package that was on screen, not the one replacing it.
        <PackageDetail
          canWrite={canWrite}
          facets={facets}
          key={usage.data.id}
          orgSlug={orgSlug}
          pkg={usage.data}
        />
      )}
    </div>
  )
}

function CatalogSummary({
  ecosystems,
  facets,
  totals,
}: {
  ecosystems: Set<string>
  facets: UsageFacets
  totals: Record<string, number>
}) {
  const selected =
    ecosystems.size +
    facets.environment.size +
    facets.project_type.size +
    facets.team.size
  if (selected > 0) {
    return <>{`${selected} filter${selected === 1 ? '' : 's'} applied`}</>
  }
  const entries = Object.entries(totals).sort(([a], [b]) => a.localeCompare(b))
  const indexed = entries.reduce((sum, [, count]) => sum + count, 0)
  if (indexed === 0) return null
  const detail = entries
    .map(([name, count]) => `${name} ${count.toLocaleString()}`)
    .join(' · ')
  return <>{`${indexed.toLocaleString()} packages indexed · ${detail}`}</>
}

function EmptyPrompt() {
  return (
    <div className="border-tertiary bg-primary rounded-lg border p-10 text-center">
      <Package className="text-tertiary mx-auto size-6" />
      <p className="text-secondary mt-3 text-sm">
        Search for a package to see every project running it, by version.
      </p>
      <p className="text-tertiary mt-1 text-xs">
        Only releases with an ingested SBoM appear here.
      </p>
    </div>
  )
}

function NoteButton({
  count,
  onClick,
}: {
  count: number
  onClick: () => void
}) {
  return (
    <button
      aria-label={`Notes (${count})`}
      className={`inline-flex h-5 items-center gap-1 rounded border px-1.5 font-mono text-[10px] ${
        count > 0
          ? 'border-action text-action bg-warning'
          : 'border-tertiary text-tertiary hover:text-secondary'
      }`}
      onClick={onClick}
      type="button"
    >
      <SquarePen className="size-2.5" />
      {count > 0 ? count : ''}
    </button>
  )
}

function OptionRow({
  ecosystem,
  meta,
  name,
  onSelect,
}: {
  ecosystem?: string
  meta?: string
  name: string
  onSelect: () => void
}) {
  return (
    <button
      className="hover:bg-secondary flex w-full items-center gap-2.5 px-4 py-2 text-left"
      onClick={onSelect}
      type="button"
    >
      {ecosystem && (
        <span className="bg-secondary text-secondary shrink-0 rounded px-1.5 font-mono text-[10px]">
          {ecosystem}
        </span>
      )}
      <span className="text-primary min-w-0 flex-1 truncate font-mono text-xs font-medium">
        {name}
      </span>
      {meta && (
        <span className="text-tertiary shrink-0 text-xs tabular-nums">
          {meta}
        </span>
      )}
    </button>
  )
}

function PackageDetail({
  canWrite,
  facets,
  orgSlug,
  pkg,
}: {
  canWrite: boolean
  facets: UsageFacets
  orgSlug: string
  pkg: ComponentUsage
}) {
  const governance = useComponentGovernance(orgSlug)
  const [notesFor, setNotesFor] = useState<ComponentUsageVersion | null>(null)
  const [advisoryFor, setAdvisoryFor] = useState<ComponentUsageVersion | null>(
    null,
  )
  const versions = useMemo(
    () => filterUsageVersions(pkg, facets),
    [pkg, facets],
  )
  // Every stat but the version count is over what the table shows, so
  // a facet narrows the numbers and the rows together. Version count
  // stays absolute: it counts what Imbi has ingested, deployed or not.
  const projects = new Set(
    versions.flatMap((v) => (v.projects ?? []).map((p) => p.id)),
  )
  const vulnerable = new Set(
    versions
      .filter((v) => v.effective_status !== null || (v.advisories ?? []).length)
      .flatMap((v) => (v.projects ?? []).map((p) => p.id)),
  )
  const filtered = !facetsAreEmpty(facets)

  return (
    <>
      <div className="border-tertiary bg-primary rounded-lg border p-[18px]">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-primary font-mono text-lg font-semibold">
                {pkg.name}
              </h2>
              <span className="bg-secondary text-secondary rounded px-1.5 py-0.5 font-mono text-[11px]">
                {pkg.ecosystem}
              </span>
              <ComponentStatusMenu
                disabled={!canWrite || governance.isPending}
                label="Mark this package"
                onSelect={(status) => governance.markComponent(pkg.id, status)}
                status={pkg.status}
              />
            </div>
            <div className="text-tertiary mt-1 font-mono text-xs">
              {pkg.purl_name}
            </div>
          </div>
          <div className="flex flex-wrap gap-8">
            <Stat label="Projects" value={String(projects.size)} />
            <Stat
              label="Versions"
              value={String(filtered ? versions.length : pkg.version_count)}
            />
            <Stat
              danger={vulnerable.size > 0}
              label="Vulnerable projects"
              value={String(vulnerable.size)}
            />
            <Stat
              label="Newest deployed"
              value={pkg.newest_deployed_version ?? '—'}
            />
          </div>
        </div>
      </div>

      <VersionTable
        canWrite={canWrite}
        governance={governance}
        onOpenAdvisory={setAdvisoryFor}
        onOpenNotes={setNotesFor}
        versions={versions}
      />

      {notesFor && (
        <ComponentNotesDialog
          canWrite={canWrite}
          componentReleaseId={notesFor.id}
          isPending={governance.isPending}
          onAddNote={(body) =>
            governance.addNote({ body, componentReleaseId: notesFor.id })
          }
          onOpenChange={(open) => !open && setNotesFor(null)}
          open
          orgSlug={orgSlug}
          purlName={pkg.purl_name}
          version={notesFor.version}
        />
      )}
      {advisoryFor && (
        <AddAdvisoryDialog
          componentReleaseId={advisoryFor.id}
          isPending={governance.isPending}
          onOpenChange={(open) => !open && setAdvisoryFor(null)}
          onRecord={({ cveId, title, url }) => {
            // Close only once it lands, so a rejected write leaves the
            // typed identifier and URL on screen next to the toast.
            void governance
              .recordAdvisory({
                componentReleaseId: advisoryFor.id,
                cveId,
                title,
                url,
              })
              .then(
                () => setAdvisoryFor(null),
                () => undefined,
              )
          }}
          open
          version={advisoryFor.version}
        />
      )}
    </>
  )
}

function PackageSearch({
  hits,
  isSearching,
  onSearch,
  onSelect,
  query,
  recent,
  search,
  setSearch,
  total,
}: {
  hits: ComponentSearchResult[]
  isSearching: boolean
  onSearch: (query: string) => void
  onSelect: (id: string) => void
  query: string
  recent: RecentPackage[]
  search: string
  setSearch: (value: string) => void
  total: number
}) {
  const [open, setOpen] = useState(false)

  const browsing = query === ''
  const hidden = Math.max(0, total - hits.length)
  return (
    // Focus is tracked on the container, not the input: tabbing from
    // the input into the option list blurs the input, and unmounting
    // the list on that blur puts the options out of keyboard reach.
    <div
      className="relative"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false)
      }}
      onFocus={() => setOpen(true)}
    >
      <Search className="text-tertiary absolute top-4 left-3.5 size-4" />
      <input
        className="border-tertiary bg-primary text-primary placeholder:text-tertiary focus:border-action h-12 w-full rounded-lg border pr-24 pl-10 text-sm outline-none"
        onChange={(e) => {
          setSearch(e.target.value)
          // Emptying the box is a request to go back to the recents
          // list, not to hold the last result set behind it.
          if (e.target.value.trim() === '') onSearch('')
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            onSearch(search.trim())
            setOpen(true)
          }
          if (e.key === 'Escape') setOpen(false)
        }}
        placeholder="Search packages by name, then press Enter — jsonschema, react, axios…"
        value={search}
      />
      {isSearching && (
        <span className="text-tertiary absolute top-3.5 right-3.5 flex items-center gap-1.5 text-xs">
          <Loader2 className="size-3.5 animate-spin" />
          Searching…
        </span>
      )}
      {open && (
        <div className="border-tertiary bg-primary absolute z-10 mt-1 max-h-80 w-full overflow-y-auto rounded-lg border py-2 shadow-lg">
          <p className="text-tertiary text-overline px-4 pb-2 tracking-wide uppercase">
            {browsing
              ? 'Recently viewed'
              : isSearching
                ? 'Searching'
                : `${total} match${total === 1 ? '' : 'es'}`}
          </p>
          {browsing
            ? recent.map((entry) => (
                <OptionRow
                  ecosystem={entry.ecosystem}
                  key={entry.id}
                  name={entry.purl_name}
                  onSelect={() => {
                    setOpen(false)
                    onSelect(entry.id)
                  }}
                />
              ))
            : hits.map((hit) => (
                <OptionRow
                  ecosystem={hit.ecosystem}
                  key={hit.id}
                  meta={`${hit.version_count} version${
                    hit.version_count === 1 ? '' : 's'
                  } · ${hit.project_count} project${
                    hit.project_count === 1 ? '' : 's'
                  }`}
                  name={hit.purl_name}
                  onSelect={() => {
                    setOpen(false)
                    onSelect(hit.id)
                  }}
                />
              ))}
          {isSearching && !browsing && hits.length === 0 && (
            <p className="text-tertiary flex items-center gap-2 px-4 py-4 text-xs">
              <Loader2 className="size-3.5 animate-spin" />
              Searching the package catalog…
            </p>
          )}
          {!isSearching && !browsing && hits.length === 0 && (
            <p className="text-tertiary px-4 py-4 text-xs">
              No indexed package matches that name. Only packages present in a
              deployed SBoM are searchable.
            </p>
          )}
          {browsing && search.trim() !== '' && (
            <p className="text-tertiary px-4 py-4 text-xs">
              Press Enter to search for “{search.trim()}”.
            </p>
          )}
          {browsing && search.trim() === '' && recent.length === 0 && (
            <p className="text-tertiary px-4 py-4 text-xs">
              Nothing viewed yet — type a package name to start.
            </p>
          )}
          {hidden > 0 && (
            <p className="border-tertiary text-tertiary mt-1 border-t px-4 pt-2 text-xs">
              {hidden} more match{hidden === 1 ? '' : 'es'} — keep typing to
              narrow
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Read the recently-viewed list, discarding anything that is not a
 * usable entry.
 *
 * `JSON.parse` succeeds for any valid JSON, so an older or hand-edited
 * value could hand back a string or an object. Filtering here keeps a
 * bad localStorage entry from blanking the whole report.
 */
function readRecent(): RecentPackage[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (entry): entry is RecentPackage =>
        typeof (entry as RecentPackage | undefined)?.id === 'string' &&
        typeof (entry as RecentPackage | undefined)?.purl_name === 'string',
    )
  } catch {
    return []
  }
}

function Stat({
  danger,
  label,
  value,
}: {
  danger?: boolean
  label: string
  value: string
}) {
  return (
    <div>
      <div className="text-tertiary text-overline tracking-wide uppercase">
        {label}
      </div>
      <div
        className={`mt-0.5 font-mono text-lg font-semibold tabular-nums ${
          danger ? 'text-danger' : 'text-primary'
        }`}
      >
        {value}
      </div>
    </div>
  )
}

function toggled(set: Set<string>, slug: string): Set<string> {
  const next = new Set(set)
  if (next.has(slug)) next.delete(slug)
  else next.add(slug)
  return next
}

function UsageSkeleton() {
  return (
    <div className="space-y-3">
      <Sk className="h-24 w-full" />
      <Sk className="h-64 w-full" />
    </div>
  )
}

// fallow-ignore-next-line complexity
function VersionRow({
  canWrite,
  expanded,
  governance,
  onOpenAdvisory,
  onOpenNotes,
  onToggle,
  version,
}: {
  canWrite: boolean
  expanded: boolean
  governance: ReturnType<typeof useComponentGovernance>
  onOpenAdvisory: (version: ComponentUsageVersion) => void
  onOpenNotes: (version: ComponentUsageVersion) => void
  onToggle: () => void
  version: ComponentUsageVersion
}) {
  const projects = version.projects ?? []
  const preview = projects.slice(0, 3).map((p) => p.name)
  return (
    <>
      <tr
        className="border-tertiary hover:bg-secondary/40 cursor-pointer border-t"
        onClick={onToggle}
      >
        <td className="px-[18px] py-2.5">
          <span className="text-primary font-mono text-xs font-semibold tabular-nums">
            {version.version}
          </span>
        </td>
        <td className="text-secondary truncate px-4 py-2.5 text-xs">
          {preview.join(', ')}
          {projects.length > preview.length &&
            `, +${projects.length - preview.length} more`}
        </td>
        {/* The menu and the notes button open their own surfaces, so
            this cell must not also toggle the row underneath them. */}
        <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
          <span className="flex items-center gap-1.5">
            <ComponentStatusMenu
              disabled={!canWrite || governance.isPending}
              label="Mark this version"
              onSelect={(status) => governance.markVersion(version.id, status)}
              status={version.status}
            />
            <NoteButton
              count={version.note_count}
              onClick={() => onOpenNotes(version)}
            />
          </span>
          {version.status_inherited && (
            <span className="text-tertiary text-[11px]">
              inherited from package
            </span>
          )}
        </td>
        <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
          <AdvisoryChips advisories={version.advisories ?? []} />
          {canWrite && (
            <button
              className="text-tertiary hover:text-primary ml-1 inline-flex items-center gap-0.5 text-[11px]"
              onClick={() => onOpenAdvisory(version)}
              type="button"
            >
              <Plus className="size-3" />
              Advisory
            </button>
          )}
        </td>
        <td className="px-4 py-2.5">
          <EnvironmentChips
            environments={version.environments ?? []}
            showCounts
          />
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-xs font-semibold tabular-nums">
          {version.project_count}
        </td>
        <td className="px-[18px] py-2.5">
          <button
            aria-expanded={expanded}
            aria-label={`Toggle projects on ${version.version}`}
            className="text-tertiary hover:text-primary flex"
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
            type="button"
          >
            <ChevronDown
              className={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
            />
          </button>
        </td>
      </tr>
      {expanded &&
        (projects.length === 0 ? (
          <tr className="bg-secondary/40">
            <td className="text-tertiary px-[18px] py-2.5 text-xs" colSpan={7}>
              No project currently deploys this version.
            </td>
          </tr>
        ) : (
          projects.map((project) => (
            <tr
              className="border-tertiary bg-secondary/40 border-t"
              key={project.id}
            >
              <td className="py-2.5 pr-4 pl-9" colSpan={2}>
                <Link
                  className="text-primary hover:text-action truncate text-xs font-medium"
                  to={`/projects/${project.id}`}
                >
                  {project.name}
                </Link>
              </td>
              <td
                className="text-secondary truncate px-4 py-2.5 text-xs"
                colSpan={2}
              >
                {(project.project_types ?? []).join(', ')}
                {project.team ? ` · ${project.team}` : ''}
              </td>
              <td className="text-secondary px-4 py-2.5 text-xs" colSpan={3}>
                {(project.environments ?? []).join(', ')}
              </td>
            </tr>
          ))
        ))}
    </>
  )
}

function VersionTable({
  canWrite,
  governance,
  onOpenAdvisory,
  onOpenNotes,
  versions,
}: {
  canWrite: boolean
  governance: ReturnType<typeof useComponentGovernance>
  onOpenAdvisory: (version: ComponentUsageVersion) => void
  onOpenNotes: (version: ComponentUsageVersion) => void
  versions: ComponentUsageVersion[]
}) {
  const { isExpanded, toggle } = useExpandedKeys()
  if (versions.length === 0) {
    return (
      <div className="border-tertiary bg-primary rounded-lg border p-11 text-center">
        <p className="text-primary text-sm font-medium">
          No deployed usage matches these filters
        </p>
        <p className="text-tertiary mt-1 text-xs">
          Clear a filter, or check whether the projects you expect have deployed
          since the last index.
        </p>
      </div>
    )
  }
  return (
    <div className="border-tertiary bg-primary overflow-x-auto rounded-lg border">
      <table className="w-full min-w-260">
        <thead>
          <tr className="bg-secondary text-secondary text-overline text-left tracking-wide uppercase">
            <th className="w-37.5 px-[18px] py-2.5 font-medium">Version</th>
            <th className="px-4 py-2.5 font-medium">Projects deployed</th>
            <th className="w-50 px-4 py-2.5 font-medium">Status</th>
            <th className="w-37.5 px-4 py-2.5 font-medium">Advisories</th>
            <th className="w-55 px-4 py-2.5 font-medium">Environments</th>
            <th className="w-18.5 px-4 py-2.5 text-right font-medium">
              Projects
            </th>
            <th className="w-11 px-[18px] py-2.5" />
          </tr>
        </thead>
        <tbody>
          {versions.map((version) => (
            <VersionRow
              canWrite={canWrite}
              expanded={isExpanded(version.id)}
              governance={governance}
              key={version.id}
              onOpenAdvisory={onOpenAdvisory}
              onOpenNotes={onOpenNotes}
              onToggle={() => toggle(version.id)}
              version={version}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function writeRecent(entries: RecentPackage[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(entries))
  } catch {
    // A full or disabled localStorage costs the reader their recents
    // list, nothing more — never the screen.
  }
}
