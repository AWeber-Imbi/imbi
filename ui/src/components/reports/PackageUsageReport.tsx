import { useEffect, useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Package,
  Plus,
  Search,
  StickyNote,
} from 'lucide-react'

import { getComponentUsage, searchComponents } from '@/api/endpoints'
import { AddAdvisoryDialog } from '@/components/packages/AddAdvisoryDialog'
import { AdvisoryChips } from '@/components/packages/AdvisoryChips'
import { ComponentNotesDialog } from '@/components/packages/ComponentNotesDialog'
import { ComponentStatusMenu } from '@/components/packages/ComponentStatusMenu'
import { EnvironmentChips } from '@/components/packages/EnvironmentChips'
import { statusLabel, statusVariant } from '@/components/packages/status'
import { useComponentGovernance } from '@/components/packages/useComponentGovernance'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Sk } from '@/components/ui/skeleton'
import { StatCard } from '@/components/ui/stat-card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useExpandedKeys } from '@/hooks/useExpandedKeys'
import { queryKeys } from '@/lib/queryKeys'
import type {
  ComponentSearchResult,
  ComponentUsage,
  ComponentUsageVersion,
} from '@/types'

/** localStorage key for the recently-viewed package list. */
const RECENT_KEY = 'imbi.packageUsage.recent'
const RECENT_LIMIT = 8

interface RecentPackage {
  id: string
  purl_name: string
}

/**
 * One row of the search dropdown.
 *
 * `project_count` is optional because the recently-viewed entries are
 * read back from localStorage and carry no count. Rendering a zero
 * there reads as "no projects use this package".
 */
interface SearchOption {
  id: string
  project_count?: number
  purl_name: string
  status?: ComponentSearchResult['status']
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
  const debounced = useDebouncedValue(search, 250)
  const [recent, setRecent] = useState<RecentPackage[]>(readRecent)

  const results = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      searchComponents(orgSlug, { limit: 25, q: debounced }, signal),
    queryKey: queryKeys.componentSearch(orgSlug, debounced, ''),
  })

  // The catalog line's counts. Same query key as the unfiltered search
  // the screen makes on load, so this shares that cache entry rather
  // than issuing a second request — and keeps the counts on screen
  // while the reader types, when the API stops returning them.
  const catalog = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => searchComponents(orgSlug, { limit: 25 }, signal),
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
        { id: pkg.id, purl_name: pkg.purl_name },
        ...prev.filter((entry) => entry.id !== pkg.id),
      ].slice(0, RECENT_LIMIT)
      writeRecent(next)
      return next
    })
  }, [usage.data])

  const select = (id: string) => {
    setParams(id ? { component: id } : {})
    setSearch('')
  }

  return (
    <div className="space-y-5">
      <PackageSearch
        onSelect={select}
        options={pickOptions(results.data?.data, recent, debounced)}
        search={search}
        setSearch={setSearch}
      />
      {!componentId && (
        <EmptyPrompt totals={catalog.data?.ecosystem_totals ?? {}} />
      )}
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
          key={usage.data.id}
          orgSlug={orgSlug}
          pkg={usage.data}
        />
      )}
    </div>
  )
}

function EmptyPrompt({ totals }: { totals: Record<string, number> }) {
  const catalog = Object.entries(totals).sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="border-tertiary bg-primary rounded-lg border p-10 text-center">
      <Package className="text-tertiary mx-auto size-6" />
      <p className="text-secondary mt-3 text-sm">
        Search for a package to see every project running it, by version.
      </p>
      {catalog.length > 0 && (
        <p className="text-tertiary mt-2 text-xs">
          Indexed:{' '}
          {catalog
            .map(([ecosystem, count]) => `${count} ${ecosystem}`)
            .join(' · ')}
        </p>
      )}
      <p className="text-tertiary mt-1 text-xs">
        Only releases with an ingested SBoM appear here.
      </p>
    </div>
  )
}

function PackageDetail({
  canWrite,
  orgSlug,
  pkg,
}: {
  canWrite: boolean
  orgSlug: string
  pkg: ComponentUsage
}) {
  const governance = useComponentGovernance(orgSlug)
  const [notesFor, setNotesFor] = useState<ComponentUsageVersion | null>(null)
  const [advisoryFor, setAdvisoryFor] = useState<ComponentUsageVersion | null>(
    null,
  )

  return (
    <>
      <div className="border-tertiary bg-primary rounded-lg border p-[18px]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <div className="text-primary font-mono text-sm">
              {pkg.purl_name}
            </div>
            <div className="text-tertiary mt-1 text-xs">
              {pkg.ecosystem}
              {pkg.description ? ` · ${pkg.description}` : ''}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-tertiary text-xs">Mark this package</span>
            <ComponentStatusMenu
              disabled={!canWrite || governance.isPending}
              label="Package status"
              onSelect={(status) => governance.markComponent(pkg.id, status)}
              status={pkg.status}
            />
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Projects" value={String(pkg.project_count)} />
          <StatCard label="Versions" value={String(pkg.version_count)} />
          <StatCard
            label="Projects at risk"
            value={String(pkg.vulnerable_project_count)}
            valueColor={
              pkg.vulnerable_project_count > 0
                ? 'var(--text-color-danger)'
                : undefined
            }
          />
          <StatCard
            label="Newest deployed"
            value={pkg.newest_deployed_version ?? '—'}
          />
        </div>
      </div>

      <VersionTable
        canWrite={canWrite}
        governance={governance}
        onOpenAdvisory={setAdvisoryFor}
        onOpenNotes={setNotesFor}
        versions={pkg.versions}
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
  onSelect,
  options,
  search,
  setSearch,
}: {
  onSelect: (id: string) => void
  options: SearchOption[]
  search: string
  setSearch: (value: string) => void
}) {
  const [focused, setFocused] = useState(false)
  return (
    // Focus is tracked on the container, not the input: tabbing from
    // the input into the option list blurs the input, and unmounting
    // the list on that blur puts the options out of keyboard reach.
    <div
      className="relative"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false)
      }}
      onFocus={() => setFocused(true)}
    >
      <Search className="text-tertiary absolute top-2.5 left-3 size-3.5" />
      <Input
        className="pl-9"
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search packages by name or purl"
        value={search}
      />
      {focused && options.length > 0 && (
        <div className="border-tertiary bg-primary absolute z-10 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border p-1 shadow-lg">
          {options.map((option) => (
            <button
              className="hover:bg-secondary flex w-full items-center justify-between gap-3 rounded px-2 py-1.5 text-left"
              key={option.id}
              onClick={() => onSelect(option.id)}
              type="button"
            >
              <span className="text-primary min-w-0 flex-1 truncate font-mono text-xs">
                {option.purl_name}
              </span>
              {option.status && (
                <Badge variant={statusVariant(option.status)}>
                  {statusLabel(option.status)}
                </Badge>
              )}
              {option.project_count !== undefined && (
                <span className="text-tertiary shrink-0 font-mono text-xs tabular-nums">
                  {option.project_count}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * The dropdown's contents: search hits while the reader is typing,
 * their recently-viewed packages while the box is empty.
 */
function pickOptions(
  hits: ComponentSearchResult[] | undefined,
  recent: RecentPackage[],
  query: string,
): SearchOption[] {
  if (query.trim()) return hits ?? []
  return recent.map((entry) => ({
    id: entry.id,
    purl_name: entry.purl_name,
  }))
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

function UsageSkeleton() {
  return (
    <div className="space-y-3">
      <Sk className="h-32 w-full" />
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
  return (
    <>
      <tr className="border-tertiary border-t">
        <td className="px-[18px] py-2">
          <button
            aria-label={`Toggle projects on ${version.version}`}
            className="text-tertiary hover:text-primary flex items-center gap-2"
            onClick={onToggle}
            type="button"
          >
            {expanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <span className="text-primary font-mono text-xs">
              {version.version}
            </span>
          </button>
        </td>
        <td className="px-4 py-2">
          <ComponentStatusMenu
            disabled={!canWrite || governance.isPending}
            label="Version status"
            onSelect={(status) => governance.markVersion(version.id, status)}
            status={version.status}
          />
          {version.status_inherited && (
            <span className="text-tertiary ml-2 text-[11px]">
              inherited from package
            </span>
          )}
        </td>
        <td className="px-4 py-2">
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
        <td className="px-4 py-2">
          <EnvironmentChips
            environments={version.environments ?? []}
            showCounts
          />
        </td>
        <td className="px-4 py-2 text-center font-mono text-xs tabular-nums">
          {version.project_count}
        </td>
        <td className="px-[18px] py-2 text-right">
          <button
            className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
            onClick={() => onOpenNotes(version)}
            type="button"
          >
            <StickyNote className="size-3.5" />
            {version.note_count}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-secondary/40">
          <td className="px-[18px] py-2" colSpan={6}>
            {(version.projects ?? []).length === 0 ? (
              <p className="text-tertiary text-xs">
                No project currently deploys this version.
              </p>
            ) : (
              <ul className="space-y-1">
                {(version.projects ?? []).map((project) => (
                  <li
                    className="flex flex-wrap items-baseline gap-2 text-xs"
                    key={project.id}
                  >
                    <span className="text-primary font-medium">
                      {project.name}
                    </span>
                    <span className="text-tertiary">{project.team}</span>
                    <span className="text-tertiary">
                      {(project.project_types ?? []).join(', ')}
                    </span>
                    <span className="text-secondary">
                      {(project.environments ?? []).join(', ')}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
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
  return (
    <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
      <table className="w-full">
        <thead>
          <tr className="text-tertiary text-overline text-left tracking-wide uppercase">
            <th className="px-[18px] py-2 font-medium">Version</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Advisories</th>
            <th className="px-4 py-2 font-medium">Environments</th>
            <th className="px-4 py-2 text-center font-medium">Projects</th>
            <th className="px-[18px] py-2 text-right font-medium">Notes</th>
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
