import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { Info, TrendingUp, X } from 'lucide-react'

import { getDocumentAnalytics, listDocumentReaders } from '@/api/endpoints'
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { UserIdentity } from '@/components/ui/user-identity'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { DocumentAnalytics, DocumentReader } from '@/types'

import { relativeShort } from './documentsHelpers'
import {
  BAND_BAR,
  BAND_CHIP,
  BAND_LABEL,
  bandCounts,
  bandFor,
  formatDwell,
} from './readershipHelpers'
import { ReadershipSparkline } from './ReadershipSparkline'

interface Props {
  displayNames?: Map<string, string>
  documentId: string
  orgSlug: string
}

interface TabProps {
  analytics: DocumentAnalytics
  displayNames?: Map<string, string>
  readers?: DocumentReader[]
  /**
   * The reader list came back. Until it does, `readers` is undefined
   * for want of an answer rather than for want of readers, so the
   * "nobody has read this" copy must stay hidden.
   */
  readersLoaded: boolean
}

/** Avatars shown before the overflow chip in the byline stack. */
const STACK_SIZE = 3
/** A quarter of history — enough for the trend to show a shape. */
const TREND_DAYS = 90

/**
 * Readership for one document: a count in the byline that opens into
 * the detail.
 *
 * Numbers cover human reads only — agent fetches (MCP, Assistant,
 * Slackbot, API) are recorded but filtered out server-side, so this
 * never reports a document as widely read because an agent indexed it.
 *
 * The reader list is only requested when the caller is allowed to see
 * it (`identities_visible`); a 403 is a legitimate answer here, not an
 * error worth surfacing. When it is allowed the list is fetched up
 * front, because the byline shows reader avatars whether or not anyone
 * opens the panel.
 */
export function DocumentReadershipPopover({
  displayNames,
  documentId,
  orgSlug,
}: Props) {
  const [tab, setTab] = useState<'engagement' | 'views'>('views')

  const { data: analytics } = useQuery({
    enabled: !!orgSlug && !!documentId,
    queryFn: ({ signal }) =>
      getDocumentAnalytics(orgSlug, documentId, signal, TREND_DAYS),
    queryKey: queryKeys.documentAnalytics(orgSlug, documentId, TREND_DAYS),
    retry: false,
    staleTime: 60_000,
  })

  const { data: readers, isSuccess: readersLoaded } = useQuery({
    enabled: !!analytics?.identities_visible,
    queryFn: ({ signal }) => listDocumentReaders(orgSlug, documentId, signal),
    queryKey: queryKeys.documentReaders(orgSlug, documentId),
    retry: false,
    staleTime: 60_000,
  })

  if (!analytics) return null

  return (
    <div className="flex items-center gap-2.5">
      <Popover>
        <PopoverTrigger
          className="text-secondary hover:bg-secondary hover:text-primary data-[state=open]:bg-secondary data-[state=open]:text-primary inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] transition-colors"
          type="button"
        >
          <TrendingUp className="size-3.5" />
          <span className="tabular-nums">{analytics.readers}</span>
          {analytics.readers === 1 ? 'reader' : 'readers'}
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="border-tertiary bg-primary w-[396px] rounded-xl p-0 shadow-lg"
        >
          <div className="flex items-center justify-between px-4 pt-4">
            <div className="text-primary text-[15px] font-medium">
              Readership
            </div>
            <PopoverClose
              aria-label="Close readership"
              className="text-tertiary hover:bg-secondary hover:text-primary cursor-pointer rounded p-1 transition-colors"
            >
              <X className="size-3.5" />
            </PopoverClose>
          </div>

          <div className="px-4 pt-3 pb-3.5">
            <SegmentedControl
              ariaLabel="Readership view"
              onValueChange={(value) => setTab(value as 'engagement' | 'views')}
              value={tab}
            >
              <SegmentedControlItem value="views">Views</SegmentedControlItem>
              <SegmentedControlItem value="engagement">
                Engagement
              </SegmentedControlItem>
            </SegmentedControl>
          </div>

          {tab === 'views' ? (
            <ViewsTab
              analytics={analytics}
              displayNames={displayNames}
              readers={readers}
              readersLoaded={readersLoaded}
            />
          ) : (
            <EngagementTab
              analytics={analytics}
              displayNames={displayNames}
              readers={readers}
              readersLoaded={readersLoaded}
            />
          )}

          <div className="border-tertiary bg-tertiary border-t px-4 py-2.5">
            <Link
              className="text-action block text-center text-[12.5px] font-medium no-underline hover:underline"
              to="/reports/document-readership"
            >
              View full readership report
            </Link>
          </div>
        </PopoverContent>
      </Popover>

      <ReaderAvatarStack
        displayNames={displayNames}
        readers={readers}
        total={analytics.readers}
      />
    </div>
  )
}

function BandTile({
  band,
  count,
}: {
  band: keyof typeof BAND_CHIP
  count: number
}) {
  return (
    <div className={cn('flex-1 rounded-lg border px-3 py-2', BAND_CHIP[band])}>
      <div className="text-[17px] font-semibold tabular-nums">{count}</div>
      <div className="text-[11.5px]">{BAND_LABEL[band]}</div>
    </div>
  )
}

function EngagementRow({
  displayNames,
  estimate,
  reader,
}: {
  displayNames?: Map<string, string>
  estimate: number
  reader: DocumentReader
}) {
  const band = bandFor(reader, estimate)
  return (
    <div className="border-tertiary grid grid-cols-[1fr_62px_62px] items-center gap-x-2.5 border-t py-2">
      <div className="min-w-0">
        <UserIdentity
          displayNames={displayNames}
          email={reader.principal}
          size="small"
        />
        <div
          aria-label={`${reader.max_scroll_pct}% scroll depth`}
          className="bg-secondary mt-1.5 h-1 w-24 overflow-hidden rounded-full"
          role="img"
        >
          <div
            className={cn('h-full rounded-full', BAND_BAR[band])}
            style={{ width: `${reader.max_scroll_pct}%` }}
          />
        </div>
      </div>
      <div className="text-secondary text-right text-[12px] tabular-nums">
        {formatDwell(reader.engaged_seconds)}
      </div>
      <div className="text-secondary text-right text-[12px] tabular-nums">
        {reader.max_scroll_pct}%
      </div>
    </div>
  )
}

function EngagementTab({
  analytics,
  displayNames,
  readers,
  readersLoaded,
}: TabProps) {
  const counts = bandCounts(readers ?? [], analytics.estimated_read_seconds)
  return (
    <div className="px-4 pb-4">
      <div className="flex gap-2">
        <BandTile band="engaged" count={counts.engaged} />
        <BandTile band="skimmed" count={counts.skimmed} />
        <BandTile band="brief" count={counts.brief} />
      </div>

      <div className="text-tertiary mt-2.5 text-[11.5px]">
        Median {formatDwell(analytics.median_engaged_seconds)} · p90{' '}
        {formatDwell(analytics.p90_engaged_seconds)} ·{' '}
        <span className="tabular-nums">
          {Math.round(analytics.completion_rate * 100)}%
        </span>{' '}
        completion
      </div>

      {analytics.identities_visible ? (
        readers && readers.length > 0 ? (
          <>
            <div className="text-overline text-tertiary mt-4 grid grid-cols-[1fr_62px_62px] gap-x-2.5 uppercase">
              <div>Reader</div>
              <div className="text-right">Time</div>
              <div className="text-right">Depth</div>
            </div>
            {readers.map((reader) => (
              <EngagementRow
                displayNames={displayNames}
                estimate={analytics.estimated_read_seconds}
                key={reader.principal}
                reader={reader}
              />
            ))}
          </>
        ) : (
          readersLoaded && <NoReaders />
        )
      ) : (
        <IdentitiesHidden />
      )}
    </div>
  )
}

function IdentitiesHidden() {
  return (
    <div className="text-tertiary mt-3 text-[12px]">
      Individual readers are not shown for this organization.
    </div>
  )
}

function NoReaders() {
  return (
    <div className="text-tertiary mt-3 text-[12px]">
      No individual reads recorded yet.
    </div>
  )
}

function ReaderAvatarStack({
  displayNames,
  readers,
  total,
}: {
  displayNames?: Map<string, string>
  readers?: DocumentReader[]
  total: number
}) {
  if (!readers || readers.length === 0) return null
  const shown = readers.slice(0, STACK_SIZE)
  const overflow = Math.max(0, total - shown.length)
  return (
    <div className="hidden items-center sm:flex">
      {shown.map((reader, index) => (
        <span
          className={cn(
            // ``inline-flex`` so the ring hugs the avatar. A plain inline
            // span is sized by line-height, which drew the ring offset
            // from the image it is meant to outline.
            'ring-primary inline-flex rounded-full ring-2',
            index > 0 && '-ml-1.5',
          )}
          key={reader.principal}
        >
          <UserIdentity
            displayNames={displayNames}
            email={reader.principal}
            hideName
            size="small"
          />
        </span>
      ))}
      {overflow > 0 && (
        <span className="bg-secondary text-tertiary ring-primary -ml-1.5 inline-flex size-5 items-center justify-center rounded-full text-[9.5px] font-semibold tabular-nums ring-2">
          +{overflow}
        </span>
      )}
    </div>
  )
}

function RecentReaderRow({
  displayNames,
  estimate,
  reader,
}: {
  displayNames?: Map<string, string>
  estimate: number
  reader: DocumentReader
}) {
  const band = bandFor(reader, estimate)
  return (
    <div className="border-tertiary flex items-center gap-2.5 border-t py-1.5">
      <div className="min-w-0 flex-1">
        <UserIdentity
          displayNames={displayNames}
          email={reader.principal}
          size="small"
        />
        <div className="text-tertiary mt-0.5 text-[11.5px]">
          {relativeShort(reader.last_read_at)}
        </div>
      </div>
      <span
        className={cn(
          'rounded border px-1.5 py-px text-[11.5px] font-medium',
          BAND_CHIP[band],
        )}
      >
        {BAND_LABEL[band]}
      </span>
    </div>
  )
}

function Tile({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-tertiary flex-1 rounded-lg px-3 py-2.5">
      <div className="text-primary text-[22px] leading-tight font-semibold tabular-nums">
        {value}
      </div>
      <div className="text-secondary mt-0.5 text-[11.5px]">{label}</div>
    </div>
  )
}

function ViewsTab({
  analytics,
  displayNames,
  readers,
  readersLoaded,
}: TabProps) {
  // Non-web surfaces are excluded from every headline number; show them
  // separately so agent traffic stays visible without inflating reads.
  const agentViews = analytics.by_surface
    .filter((entry) => entry.surface !== 'web')
    .reduce((sum, entry) => sum + entry.views, 0)

  return (
    <div className="px-4 pb-4">
      <div className="flex gap-2.5">
        <Tile label="views (all-time)" value={analytics.views} />
        <Tile label="unique readers" value={analytics.readers} />
      </div>

      <ReadershipSparkline trend={analytics.trend} />

      {agentViews > 0 && (
        <div className="text-tertiary mt-1.5 text-[11.5px]">
          Plus <span className="tabular-nums">{agentViews}</span> agent
          {agentViews === 1 ? ' fetch' : ' fetches'}, not counted above.
        </div>
      )}

      <div className="mt-4 flex items-center justify-between">
        <div className="text-overline text-tertiary uppercase">
          Recent readers
        </div>
        <div
          className="text-tertiary flex items-center gap-1 text-[11.5px]"
          title="Engagement is measured from time on page and scroll depth."
        >
          Engagement
          <Info className="size-3" />
        </div>
      </div>

      {analytics.identities_visible ? (
        readers && readers.length > 0 ? (
          readers.map((reader) => (
            <RecentReaderRow
              displayNames={displayNames}
              estimate={analytics.estimated_read_seconds}
              key={reader.principal}
              reader={reader}
            />
          ))
        ) : (
          readersLoaded && <NoReaders />
        )
      ) : (
        <IdentitiesHidden />
      )}
    </div>
  )
}
