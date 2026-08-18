import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Download, ShieldCheck } from 'lucide-react'

import { getProblemPackages } from '@/api/endpoints'
import { AdvisoryChips } from '@/components/packages/AdvisoryChips'
import { ComponentNotesDialog } from '@/components/packages/ComponentNotesDialog'
import { EnvironmentChips } from '@/components/packages/EnvironmentChips'
import { statusLabel, statusVariant } from '@/components/packages/status'
import { useComponentGovernance } from '@/components/packages/useComponentGovernance'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FilterPopover } from '@/components/ui/filter-popover'
import { Sk } from '@/components/ui/skeleton'
import { StatCard } from '@/components/ui/stat-card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useExpandableRows } from '@/hooks/useExpandableRows'
import { queryKeys } from '@/lib/queryKeys'
import type { ProblemPackageRow } from '@/types'

import {
  applyFacets,
  EMPTY_FACETS,
  exportCsv,
  type FacetKey,
  facetOptions,
  type Facets,
  summarize,
} from './problem-packages'

export function ProblemPackagesReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const { user } = useAuth()
  const canWrite =
    user?.is_admin === true ||
    (user?.permissions ?? []).includes('component:write')

  const [facets, setFacets] = useState<Facets>(EMPTY_FACETS)
  const [notesFor, setNotesFor] = useState<null | ProblemPackageRow>(null)
  const governance = useComponentGovernance(orgSlug)

  const { data, isError, isLoading } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProblemPackages(orgSlug, signal),
    queryKey: queryKeys.problemPackages(orgSlug),
  })

  const rows = data?.rows ?? []
  const filtered = useMemo(() => applyFacets(rows, facets), [rows, facets])
  const stats = useMemo(() => summarize(filtered), [filtered])

  const toggle = (facet: FacetKey) => (slug: string) =>
    setFacets((prev) => {
      const next = new Set(prev[facet])
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return { ...prev, [facet]: next }
    })

  if (isLoading) return <Sk className="h-96 w-full" />
  if (isError) {
    return (
      <p className="text-danger text-sm">
        Could not load the problem-packages report.
      </p>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Projects affected" value={String(stats.projects)} />
        <StatCard
          label="Forbidden versions"
          value={String(stats.forbidden)}
          valueColor={
            stats.forbidden > 0 ? 'var(--text-color-danger)' : undefined
          }
        />
        <StatCard
          label="Deprecated versions"
          value={String(stats.deprecated)}
        />
        <StatCard label="Known advisories" value={String(stats.advisories)} />
      </div>

      <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
        <Toolbar
          facets={facets}
          filteredCount={filtered.length}
          onExport={() => exportCsv(filtered)}
          onReset={() => setFacets(EMPTY_FACETS)}
          rows={rows}
          toggle={toggle}
          totalCount={rows.length}
        />
        <FindingsTable
          canWrite={canWrite}
          onOpenNotes={setNotesFor}
          rows={filtered}
        />
      </div>

      {data?.truncated && (
        <p className="text-tertiary text-xs">
          Showing the first {rows.length} findings — narrow the scope to see the
          rest.
        </p>
      )}
      <p className="text-tertiary text-xs">
        Only releases with an ingested SBoM appear here; a release deployed
        without one has no recorded dependencies.
      </p>

      {notesFor && (
        <ComponentNotesDialog
          canWrite={canWrite}
          componentReleaseId={notesFor.component_release_id}
          isPending={governance.isPending}
          onAddNote={(body) =>
            governance.addNote({
              body,
              componentReleaseId: notesFor.component_release_id,
            })
          }
          onOpenChange={(open) => !open && setNotesFor(null)}
          open
          orgSlug={orgSlug}
          purlName={notesFor.purl_name}
          version={notesFor.version}
        />
      )}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="p-10 text-center">
      <ShieldCheck className="text-success mx-auto size-6" />
      <p className="text-secondary mt-3 text-sm">
        Nothing deployed is deprecated, forbidden, or carrying a known advisory.
      </p>
    </div>
  )
}

// fallow-ignore-next-line complexity
function FindingRow({
  canWrite,
  expanded,
  onOpenNotes,
  onToggle,
  row,
}: {
  canWrite: boolean
  expanded: boolean
  onOpenNotes: (row: ProblemPackageRow) => void
  onToggle: () => void
  row: ProblemPackageRow
}) {
  return (
    <>
      <tr className="border-tertiary border-t align-top">
        <td className="px-[18px] py-2">
          <button
            aria-label={`Toggle detail for ${row.project_name}`}
            className="text-tertiary hover:text-primary flex items-center gap-2"
            onClick={onToggle}
            type="button"
          >
            {expanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <span className="text-primary text-xs font-medium">
              {row.project_name}
            </span>
          </button>
        </td>
        <td className="text-secondary px-4 py-2 text-xs">{row.team ?? '—'}</td>
        <td className="px-4 py-2 font-mono text-xs">{row.purl_name}</td>
        <td className="px-4 py-2 font-mono text-xs">{row.version}</td>
        <td className="px-4 py-2">
          {row.status ? (
            <Badge variant={statusVariant(row.status)}>
              {statusLabel(row.status)}
            </Badge>
          ) : (
            <span className="text-tertiary text-xs">—</span>
          )}
          {row.status_inherited && (
            <span className="text-tertiary ml-1 text-[11px]">inherited</span>
          )}
        </td>
        <td className="px-4 py-2">
          <AdvisoryChips advisories={row.advisories ?? []} />
        </td>
        <td className="px-4 py-2">
          <EnvironmentChips environments={row.environments ?? []} />
        </td>
        <td className="px-[18px] py-2 text-right">
          <button
            className="text-tertiary hover:text-primary text-xs"
            onClick={() => onOpenNotes(row)}
            type="button"
          >
            {row.note_count}
            {canWrite ? ' +' : ''}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-secondary/40">
          <td className="px-[18px] py-2 text-xs" colSpan={8}>
            <span className="text-tertiary">Project types: </span>
            <span className="text-secondary">
              {(row.project_types ?? []).join(', ') || '—'}
            </span>
            {(row.advisories ?? []).length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {(row.advisories ?? []).map((advisory) => (
                  <li key={advisory.cve_id}>
                    <a
                      className="text-action"
                      href={advisory.url}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      {advisory.cve_id}
                    </a>
                    {advisory.title ? ` — ${advisory.title}` : ''}
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

function FindingsTable({
  canWrite,
  onOpenNotes,
  rows,
}: {
  canWrite: boolean
  onOpenNotes: (row: ProblemPackageRow) => void
  rows: ProblemPackageRow[]
}) {
  const { expanded, toggleExpanded } = useExpandableRows()
  if (rows.length === 0) return <EmptyState />
  return (
    <table className="w-full">
      <thead>
        <tr className="text-tertiary text-overline text-left tracking-wide uppercase">
          <th className="px-[18px] py-2 font-medium">Project</th>
          <th className="px-4 py-2 font-medium">Team</th>
          <th className="px-4 py-2 font-medium">Package</th>
          <th className="px-4 py-2 font-medium">Version</th>
          <th className="px-4 py-2 font-medium">Status</th>
          <th className="px-4 py-2 font-medium">Advisories</th>
          <th className="px-4 py-2 font-medium">Environments</th>
          <th className="px-[18px] py-2 text-right font-medium">Notes</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <FindingRow
            canWrite={canWrite}
            expanded={expanded.has(index)}
            key={`${row.project_id}:${row.component_release_id}`}
            onOpenNotes={onOpenNotes}
            onToggle={() => toggleExpanded(index)}
            row={row}
          />
        ))}
      </tbody>
    </table>
  )
}

const FACET_LABELS: Record<FacetKey, string> = {
  ecosystems: 'package type',
  environments: 'environment',
  findings: 'finding',
  projectTypes: 'project type',
  teams: 'team',
}

function Toolbar({
  facets,
  filteredCount,
  onExport,
  onReset,
  rows,
  toggle,
  totalCount,
}: {
  facets: Facets
  filteredCount: number
  onExport: () => void
  onReset: () => void
  rows: ProblemPackageRow[]
  toggle: (facet: FacetKey) => (slug: string) => void
  totalCount: number
}) {
  const active = (Object.keys(facets) as FacetKey[]).some(
    (key) => facets[key].size > 0,
  )
  return (
    <div className="border-tertiary flex flex-wrap items-center gap-4 border-b px-[18px] py-2.5">
      {(Object.keys(FACET_LABELS) as FacetKey[]).map((key) => (
        <div className="flex items-center gap-1" key={key}>
          <span className="text-tertiary text-sm font-medium capitalize">
            {FACET_LABELS[key]}
          </span>
          <FilterPopover
            activeFilters={facets[key]}
            label={FACET_LABELS[key]}
            onToggle={toggle(key)}
            options={facetOptions(rows, facets, key)}
          />
        </div>
      ))}
      <span className="text-tertiary text-xs">
        {filteredCount} of {totalCount} findings
      </span>
      <div className="ml-auto flex items-center gap-2">
        {active && (
          <button
            className="text-action text-xs"
            onClick={onReset}
            type="button"
          >
            Reset
          </button>
        )}
        <Button onClick={onExport} size="sm" type="button" variant="ghost">
          <Download className="size-3.5" />
          CSV
        </Button>
      </div>
    </div>
  )
}
