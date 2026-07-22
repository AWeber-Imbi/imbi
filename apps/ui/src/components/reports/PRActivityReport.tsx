import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'

import { getPRActivity } from '@/api/endpoints'
import type { PRActivityResponse, PRActivityRow } from '@/api/endpoints'
import { Sk } from '@/components/ui/skeleton'
import { UserIdentity } from '@/components/ui/user-identity'
import { useOrganization } from '@/contexts/OrganizationContext'

export function PRActivityReport() {
  const orgSlug = useOrgSlug()
  const [since, setSince] = useState(defaultSince)
  const [appliedSince, setAppliedSince] = useState(since)
  const { data, error, isFetching, loading, refetch, rows } = usePRActivity(
    orgSlug,
    appliedSince,
  )

  return (
    <div className="flex flex-col gap-5">
      <Toolbar
        appliedSince={appliedSince}
        data={data}
        error={error}
        isFetching={isFetching}
        onSinceChange={setSince}
        orgSlug={orgSlug}
        refetch={refetch}
        rows={rows}
        setAppliedSince={setAppliedSince}
        since={since}
      />

      {/* Table card */}
      <div className="border-tertiary bg-primary overflow-hidden rounded-lg border">
        <ActivityTableCard
          appliedSince={appliedSince}
          error={error}
          loading={loading}
          refetch={refetch}
          rows={rows}
        />
      </div>
    </div>
  )
}

function ActivityRowsSkeleton() {
  return (
    <table aria-busy className="w-full text-sm">
      <tbody>
        {Array.from({ length: 8 }, (_, i) => (
          <tr className="border-tertiary border-b last:border-0" key={i}>
            <td className="px-[18px] py-2.5">
              <div className="flex items-center gap-2">
                <Sk h={20} r={999} w={20} />
                <Sk line w={120} />
              </div>
            </td>
            <td className="px-4 py-2.5">
              <div className="flex justify-end">
                <Sk h={16} r={3} w="70%" />
              </div>
            </td>
            <td className="px-[18px] py-2.5">
              <div className="flex justify-end">
                <Sk h={16} r={3} w="70%" />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ActivityTable({ rows }: { rows: PRActivityRow[] }) {
  const maxCreated = rows.reduce((m, r) => Math.max(m, r.created), 0)
  const maxMerged = rows.reduce((m, r) => Math.max(m, r.merged), 0)
  const totalCreated = rows.reduce((s, r) => s + r.created, 0)
  const totalMerged = rows.reduce((s, r) => s + r.merged, 0)
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-tertiary border-b">
          <th className="text-overline text-tertiary px-[18px] py-2.5 text-left font-normal tracking-wide uppercase">
            Member
          </th>
          <th className="text-overline text-tertiary w-48 px-4 py-2.5 text-right font-normal tracking-wide uppercase">
            Created
          </th>
          <th className="text-overline text-tertiary w-48 px-[18px] py-2.5 text-right font-normal tracking-wide uppercase">
            Merged ↓
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            className={`border-tertiary hover:bg-secondary transition-colors ${
              i === rows.length - 1 ? 'border-0' : 'border-b'
            }`}
            key={row.login}
          >
            <td className="px-[18px] py-2.5">
              <UserIdentity
                actor={row.login}
                displayName={row.display_name}
                email={row.email}
                size="small"
              />
            </td>
            <td className="px-4 py-2.5">
              <CountCell max={maxCreated} value={row.created} />
            </td>
            <td className="px-[18px] py-2.5">
              <CountCell max={maxMerged} value={row.merged} />
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-tertiary border-t">
          <td className="text-secondary px-[18px] py-3 text-xs font-medium tracking-wide uppercase">
            Total ({rows.length})
          </td>
          <td className="text-primary px-4 py-3 text-right font-mono text-xs tabular-nums">
            {totalCreated}
          </td>
          <td className="text-primary px-[18px] py-3 text-right font-mono text-xs tabular-nums">
            {totalMerged}
          </td>
        </tr>
      </tfoot>
    </table>
  )
}

function ActivityTableCard({
  appliedSince,
  error,
  loading,
  refetch,
  rows,
}: {
  appliedSince: string
  error: unknown
  loading: boolean
  refetch: () => Promise<unknown>
  rows: PRActivityRow[]
}) {
  if (loading) return <ActivityRowsSkeleton />
  if (error) {
    return (
      <div className="text-danger py-10 text-center text-sm">
        Failed to load PR activity.{' '}
        <button className="underline" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div className="text-tertiary py-10 text-center text-sm">
        No pull request activity since {appliedSince}.
      </div>
    )
  }
  return <ActivityTable rows={rows} />
}

/** Apply the chosen `since`; refetch directly when it is unchanged. */
function applySince(
  since: string,
  appliedSince: string,
  setAppliedSince: (value: string) => void,
  refetch: () => Promise<unknown>,
) {
  if (since === appliedSince) {
    void refetch()
  } else {
    setAppliedSince(since)
  }
}

/** Number with an amber bar sized to its share of the column max. */
function CountCell({ max, value }: { max: number; value: number }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="relative flex h-6 items-center justify-end">
      {value > 0 ? (
        <div
          className="absolute inset-y-0 left-0 rounded-sm"
          style={{
            background: 'var(--background-color-warning)',
            width: `${pct}%`,
          }}
        />
      ) : null}
      <span
        className="relative z-10 px-2 font-mono text-xs tabular-nums"
        style={{
          color:
            value > 0
              ? 'var(--text-color-primary)'
              : 'var(--text-color-tertiary)',
        }}
      >
        {value}
      </span>
    </div>
  )
}

/** Default report window: 30 days back from today. */
function defaultSince(): string {
  return isoDaysAgo(30)
}

function downloadCsv(rows: PRActivityRow[], appliedSince: string) {
  const header = ['Member', 'Login', 'Email', 'Created', 'Merged']
  const lines = rows.map((r) =>
    [r.display_name ?? r.login, r.login, r.email ?? '', r.created, r.merged]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`)
      .join(','),
  )
  const csv = [header.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.download = `pr-activity-${appliedSince}.csv`
  a.href = url
  a.click()
  URL.revokeObjectURL(url)
}

/** YYYY-MM-DD for a date `days` before today (local time). */
function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** "1 member" / "2 members" */
function pluralize(count: number, noun: string): string {
  const suffix = count === 1 ? '' : 's'
  return `${count} ${noun}${suffix}`
}

function StatusText({
  data,
  error,
  isFetching,
}: {
  data?: PRActivityResponse
  error: unknown
  isFetching: boolean
}) {
  if (isFetching) return <>Fetching…</>
  if (error) return <>Failed to load activity.</>
  if (data) return <>{`Done — ${pluralize(data.members, 'member')}.`}</>
  return null
}

function Toolbar({
  appliedSince,
  data,
  error,
  isFetching,
  onSinceChange,
  orgSlug,
  refetch,
  rows,
  setAppliedSince,
  since,
}: {
  appliedSince: string
  data?: PRActivityResponse
  error: unknown
  isFetching: boolean
  onSinceChange: (value: string) => void
  orgSlug: string
  refetch: () => Promise<unknown>
  rows: PRActivityRow[]
  setAppliedSince: (value: string) => void
  since: string
}) {
  return (
    <div className="border-tertiary bg-primary flex flex-wrap items-end gap-4 rounded-lg border p-[18px]">
      <label className="flex flex-col gap-1">
        <span className="text-overline text-tertiary tracking-wide uppercase">
          Since (inclusive)
        </span>
        <input
          className="border-tertiary bg-tertiary text-primary h-8 rounded border px-2 font-mono text-xs"
          onChange={(e) => onSinceChange(e.target.value)}
          type="date"
          value={since}
        />
      </label>
      <button
        className="bg-warning text-warning inline-flex h-8 items-center gap-1.5 rounded px-3 text-xs font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
        disabled={!orgSlug || isFetching}
        onClick={() =>
          applySince(since, appliedSince, setAppliedSince, refetch)
        }
      >
        <RefreshCw className={isFetching ? 'animate-spin' : ''} size={11} />
        Fetch activity
      </button>
      <button
        className="border-tertiary text-primary hover:bg-secondary inline-flex h-8 items-center gap-1.5 rounded border px-3 text-xs transition-colors disabled:opacity-50"
        disabled={rows.length === 0}
        onClick={() => downloadCsv(rows, appliedSince)}
      >
        <Download size={11} />
        Download CSV
      </button>
      <span className="text-tertiary ml-auto self-center text-xs">
        <StatusText data={data} error={error} isFetching={isFetching} />
      </span>
    </div>
  )
}

function useOrgSlug(): string {
  const { selectedOrganization } = useOrganization()
  return selectedOrganization?.slug ?? ''
}

function usePRActivity(orgSlug: string, since: string) {
  const query = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getPRActivity(orgSlug, since, signal),
    queryKey: ['prActivity', orgSlug, since],
    staleTime: 60_000,
  })
  return {
    ...query,
    loading: query.isFetching && !query.data,
    rows: query.data?.rows ?? [],
  }
}
