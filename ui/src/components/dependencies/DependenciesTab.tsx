import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listProjectReleases, listReleaseDependencies } from '@/api/endpoints'
import { AdminTable, type AdminTableColumn } from '@/components/ui/admin-table'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { Project, ReleaseDependencyComponent } from '@/types'

interface DependenciesTabProps {
  orgSlug: string
  project: Pick<Project, 'id' | 'slug'>
}

const COLUMNS: AdminTableColumn<ReleaseDependencyComponent>[] = [
  {
    header: 'Component',
    key: 'name',
    render: (row) => (
      <div>
        <div className="font-medium">{row.name}</div>
        <div className="text-muted-foreground text-xs">{row.purl_name}</div>
      </div>
    ),
  },
  {
    header: 'Ecosystem',
    key: 'ecosystem',
    render: (row) => (
      <span className="text-muted-foreground text-sm">{row.ecosystem}</span>
    ),
  },
  {
    header: 'Version',
    key: 'version',
    render: (row) => <code className="text-sm">{row.version}</code>,
  },
  {
    header: 'License',
    key: 'license',
    render: (row) =>
      row.license ? (
        <span className="text-sm">{row.license}</span>
      ) : (
        <span className="text-muted-foreground text-xs">—</span>
      ),
  },
  {
    header: 'Usage',
    key: 'usage',
    render: (row) => {
      const scopeClass =
        row.scope === 'optional'
          ? 'border-amber-300 bg-amber-50 text-amber-900'
          : row.scope === 'excluded'
            ? 'border-slate-300 bg-slate-50 text-slate-700'
            : 'border-emerald-300 bg-emerald-50 text-emerald-900'
      if (!row.scope && row.groups.length === 0) {
        return <span className="text-muted-foreground text-xs">—</span>
      }
      return (
        <div className="flex flex-wrap gap-1">
          {row.scope && (
            <span
              aria-label={`scope: ${row.scope}`}
              className={cn(
                'inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium',
                scopeClass,
              )}
            >
              {row.scope}
            </span>
          )}
          {row.groups.map((g) => (
            <span
              aria-label={`group: ${g}`}
              className="inline-flex items-center rounded border border-blue-300 bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-900"
              key={g}
            >
              {g}
            </span>
          ))}
        </div>
      )
    },
  },
  {
    header: 'Identifiers',
    key: 'identifiers',
    render: (row) =>
      row.identifiers.length === 0 ? (
        <span className="text-muted-foreground text-xs">—</span>
      ) : (
        <div className="space-y-1">
          {row.identifiers.map((i) => (
            <div className="text-xs" key={`${i.kind}:${i.value}`}>
              <span className="text-muted-foreground">{i.kind}:</span>{' '}
              <code>{i.value}</code>
            </div>
          ))}
        </div>
      ),
  },
]

export function DependenciesTab({ orgSlug, project }: DependenciesTabProps) {
  const releasesQuery = useQuery({
    queryFn: ({ signal }) => listProjectReleases(orgSlug, project.id, signal),
    queryKey: ['project-releases', orgSlug, project.id],
  })

  const releases = useMemo(() => releasesQuery.data ?? [], [releasesQuery.data])

  const [selectedReleaseId, setSelectedReleaseId] = useState<null | string>(
    null,
  )

  // Default the dropdown to the most-recently-created release once the
  // list lands. Keep user-driven selections sticky across refetches.
  useEffect(() => {
    if (selectedReleaseId) return
    if (releases.length === 0) return
    const sorted = [...releases].sort((a, b) =>
      a.created_at < b.created_at ? 1 : -1,
    )
    setSelectedReleaseId(sorted[0].id)
  }, [releases, selectedReleaseId])

  const dependenciesQuery = useQuery({
    enabled: selectedReleaseId !== null,
    queryFn: ({ signal }) =>
      listReleaseDependencies(
        orgSlug,
        project.id,
        selectedReleaseId as string,
        signal,
      ),
    queryKey: ['release-dependencies', orgSlug, project.id, selectedReleaseId],
  })

  if (releasesQuery.isLoading) {
    return <DependenciesTabSkeleton />
  }

  if (releasesQuery.isError) {
    return (
      <Card>
        <CardContent className="text-muted-foreground p-8 text-center">
          Failed to load releases.
        </CardContent>
      </Card>
    )
  }

  if (releases.length === 0) {
    return (
      <Card>
        <CardContent className="text-muted-foreground p-8 text-center">
          No releases yet. Once a release is created and a CycloneDX SBoM is
          ingested, its dependencies will appear here.
        </CardContent>
      </Card>
    )
  }

  const components = dependenciesQuery.data?.components ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label
          className="text-secondary text-sm font-medium"
          htmlFor="dependencies-release-select"
        >
          Release
        </label>
        <Select
          onValueChange={setSelectedReleaseId}
          value={selectedReleaseId ?? ''}
        >
          <SelectTrigger
            aria-label="Release"
            className="w-64"
            id="dependencies-release-select"
          >
            <SelectValue placeholder="Select a release" />
          </SelectTrigger>
          <SelectContent>
            {releases.map((release) => (
              <SelectItem key={release.id} value={release.id}>
                {release.tag ?? release.committish}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {dependenciesQuery.isLoading ? (
        <DependencyTableSkeleton />
      ) : dependenciesQuery.isError ? (
        <Card>
          <CardContent className="text-muted-foreground p-8 text-center">
            Failed to load dependencies.
          </CardContent>
        </Card>
      ) : (
        <AdminTable
          columns={COLUMNS}
          emptyMessage="No SBoM has been ingested for this release yet."
          getRowKey={(row) => `${row.purl_name}@${row.version}`}
          rows={components}
        />
      )}
    </div>
  )
}

/** Footprint skeleton while the releases list loads: select + table. */
function DependenciesTabSkeleton() {
  return (
    <div className="space-y-4">
      <div aria-busy className="flex items-center gap-3">
        <Sk w={48} />
        <Sk h={32} r={6} w={256} />
      </div>
      <DependencyTableSkeleton />
    </div>
  )
}

/** Footprint skeleton for the dependency table rows (6 columns). */
function DependencyTableSkeleton() {
  return (
    <Card>
      <CardContent aria-busy className="flex flex-col gap-3 p-4">
        {Array.from({ length: 8 }, (_, i) => (
          <div
            className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] items-center gap-4"
            key={i}
          >
            <div className="flex flex-col gap-1">
              <Sk line w="70%" />
              <Sk line w="45%" />
            </div>
            <Sk line w="60%" />
            <Sk line w="50%" />
            <Sk line w="55%" />
            <Sk h={20} r={4} w={56} />
            <Sk line w="65%" />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
