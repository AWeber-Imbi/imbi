import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { getOrgDocumentAnalytics } from '@/api/endpoints'
import { relativeShort } from '@/components/documents/documentsHelpers'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { useOrganization } from '@/contexts/OrganizationContext'

type Mode = 'least-read' | 'most-read' | 'never-read' | 'stale'

const MODES: { description: string; id: Mode; label: string }[] = [
  {
    description: 'Documents with the most distinct readers',
    id: 'most-read',
    label: 'Most read',
  },
  {
    description: 'Read by someone, but not for a long time',
    id: 'stale',
    label: 'Stale',
  },
  {
    description: 'Read by at least one person, fewest readers first',
    id: 'least-read',
    label: 'Least read',
  },
  {
    description: 'Never opened by anyone',
    id: 'never-read',
    label: 'Never read',
  },
]

/**
 * Org-wide document readership.
 *
 * The point of this report is the bottom of the list, not the top:
 * `never-read` and `stale` are what tell you which documentation is not
 * carrying its weight. Counts are human reads only — agent fetches are
 * filtered out server-side.
 */
export function DocumentReadershipReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [mode, setMode] = useState<Mode>('most-read')

  const { data, isPending } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) =>
      getOrgDocumentAnalytics(orgSlug, { limit: 100, mode }, signal),
    queryKey: ['orgDocumentAnalytics', orgSlug, mode],
    staleTime: 60_000,
  })

  const active = MODES.find((m) => m.id === mode) ?? MODES[0]
  // 'never-read' rows have no reads by definition, so the read columns
  // would be a column of zeroes.
  const showCounts = mode !== 'never-read'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          ariaLabel="Readership view"
          onValueChange={(value) => setMode(value as Mode)}
          value={mode}
        >
          {MODES.map((m) => (
            <SegmentedControlItem key={m.id} value={m.id}>
              {m.label}
            </SegmentedControlItem>
          ))}
        </SegmentedControl>
        <span className="text-tertiary text-xs">{active.description}</span>
      </div>

      <div className="border-tertiary bg-primary rounded-lg border">
        {isPending ? (
          <div className="text-tertiary p-4 text-sm">Loading…</div>
        ) : !data || data.length === 0 ? (
          <div className="text-tertiary p-4 text-sm">
            {mode === 'never-read'
              ? 'Every document in this organization has been read.'
              : 'No documents match this view yet.'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-tertiary text-tertiary border-b text-left">
              <tr>
                <th className="px-4 py-2 font-normal">Document</th>
                <th className="px-4 py-2 font-normal">Last read</th>
                {showCounts && (
                  <>
                    <th className="px-4 py-2 text-right font-normal">
                      Readers
                    </th>
                    <th className="px-4 py-2 text-right font-normal">Views</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="text-secondary">
              {data.map((row) => (
                <tr className="border-tertiary border-b" key={row.document_id}>
                  <td className="truncate px-4 py-2">
                    {row.title || row.document_id}
                  </td>
                  <td className="px-4 py-2">
                    {row.last_read_at ? relativeShort(row.last_read_at) : '—'}
                  </td>
                  {showCounts && (
                    <>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {row.readers}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {row.views}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
