import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { BarChart3, Clock, Eye, Users } from 'lucide-react'

import { getDocumentAnalytics, listDocumentReaders } from '@/api/endpoints'
import { queryKeys } from '@/lib/queryKeys'

import { relativeShort } from './documentsHelpers'

interface Props {
  documentId: string
  orgSlug: string
}

/**
 * One dense line of read analytics under a document, expanding into the
 * per-reader detail.
 *
 * Numbers cover human reads only — agent fetches (MCP, Assistant,
 * Slackbot, API) are recorded but filtered out server-side, so this
 * never reports a document as widely read because an agent indexed it.
 *
 * The reader list is only requested when the caller is allowed to see
 * it (`identities_visible`) *and* has expanded the panel; a 403 is a
 * legitimate answer here, not an error worth surfacing.
 */
export function DocumentAnalyticsStrip({ documentId, orgSlug }: Props) {
  const [expanded, setExpanded] = useState(false)

  const { data: analytics } = useQuery({
    enabled: !!orgSlug && !!documentId,
    queryFn: ({ signal }) => getDocumentAnalytics(orgSlug, documentId, signal),
    queryKey: queryKeys.documentAnalytics(orgSlug, documentId),
    retry: false,
    staleTime: 60_000,
  })

  const { data: readers } = useQuery({
    enabled: expanded && !!analytics?.identities_visible,
    queryFn: ({ signal }) => listDocumentReaders(orgSlug, documentId, signal),
    queryKey: queryKeys.documentReaders(orgSlug, documentId),
    retry: false,
    staleTime: 60_000,
  })

  if (!analytics) return null

  const neverRead = !analytics.last_read_at

  return (
    <div className="border-primary text-tertiary mt-5 border-t pt-2.5 text-xs">
      <button
        className="hover:text-secondary flex flex-wrap items-center gap-3 transition-colors"
        onClick={() => setExpanded((v) => !v)}
        type="button"
      >
        <span className="inline-flex items-center gap-1">
          <Clock className="size-3" />
          {neverRead
            ? 'Never read'
            : `Last read ${relativeShort(analytics.last_read_at)}`}
        </span>
        <span className="inline-flex items-center gap-1">
          <Users className="size-3" />
          <span className="tabular-nums">{analytics.readers}</span>
          {analytics.readers === 1 ? 'reader' : 'readers'}
        </span>
        <span className="inline-flex items-center gap-1">
          <Eye className="size-3" />
          <span className="tabular-nums">{analytics.views}</span>
          {analytics.views === 1 ? 'view' : 'views'}
        </span>
        <span className="inline-flex items-center gap-1">
          <BarChart3 className="size-3" />
          {formatDuration(analytics.median_engaged_seconds)} median
        </span>
      </button>

      {expanded && (
        <div className="mt-2.5 space-y-2.5">
          <dl className="grid grid-cols-2 gap-x-5 gap-y-1 sm:grid-cols-4">
            <Stat
              label="Completion"
              value={`${Math.round(analytics.completion_rate * 100)}%`}
            />
            <Stat label="Reads" value={String(analytics.reads)} />
            <Stat
              label="p90 engaged"
              value={formatDuration(analytics.p90_engaged_seconds)}
            />
            <Stat
              label="Est. read time"
              value={formatDuration(analytics.estimated_read_seconds)}
            />
          </dl>

          {analytics.by_surface.length > 1 && (
            <div className="flex flex-wrap gap-2.5">
              {analytics.by_surface.map((entry) => (
                <span key={entry.surface}>
                  {entry.surface}{' '}
                  <span className="text-secondary tabular-nums">
                    {entry.views}
                  </span>
                </span>
              ))}
            </div>
          )}

          {analytics.identities_visible ? (
            readers && readers.length > 0 ? (
              <table className="w-full">
                <thead className="text-tertiary text-left">
                  <tr>
                    <th className="font-normal">Reader</th>
                    <th className="font-normal">Last read</th>
                    <th className="text-right font-normal">Views</th>
                    <th className="text-right font-normal">Engaged</th>
                  </tr>
                </thead>
                <tbody className="text-secondary">
                  {readers.map((reader) => (
                    <tr key={reader.principal}>
                      <td className="truncate">{reader.principal}</td>
                      <td>{relativeShort(reader.last_read_at)}</td>
                      <td className="text-right tabular-nums">
                        {reader.views}
                      </td>
                      <td className="text-right tabular-nums">
                        {formatDuration(reader.engaged_seconds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div>No individual reads recorded yet.</div>
            )
          ) : (
            <div>Individual readers are not shown for this organization.</div>
          )}
        </div>
      )}
    </div>
  )
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '—'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-tertiary">{label}</dt>
      <dd className="text-secondary tabular-nums">{value}</dd>
    </div>
  )
}
