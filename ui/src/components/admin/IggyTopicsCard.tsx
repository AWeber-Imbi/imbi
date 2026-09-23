// Admin · Overview · Iggy topics.
//
// One row per topic Imbi publishes, with the sink consumer group that
// drains it. A group with more members than members that own a
// partition has a member that polls nothing, which is how a stuck sink
// shows (apache/iggy#4273).

import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, RefreshCw, Waypoints } from 'lucide-react'

import { getDashboardIggy } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sk } from '@/components/ui/skeleton'
import type { IggyTopic } from '@/types'

type SortKey =
  | 'current_offset'
  | 'lag'
  | 'members'
  | 'members_owning'
  | 'messages'
  | 'name'
  | 'stored_offset'

// @TODO: Stored and Lag always show "—". Iggy cannot return a consumer
// group offset over HTTP (apache/iggy#4279) and the Python SDK has no
// offset read (apache/iggy#3997). When either ships, fill
// `stored_offset` and `lag` in the API and the lagging state below
// starts to show.
const COLUMNS: { align: 'left' | 'right'; key: SortKey; label: string }[] = [
  { align: 'left', key: 'name', label: 'Stream / Topic' },
  { align: 'right', key: 'messages', label: 'Messages' },
  { align: 'right', key: 'current_offset', label: 'Offset' },
  { align: 'right', key: 'stored_offset', label: 'Stored' },
  { align: 'right', key: 'lag', label: 'Lag' },
  { align: 'right', key: 'members', label: 'Members' },
  { align: 'right', key: 'members_owning', label: 'Owning' },
]

// Auto-refresh choices, in seconds. 0 turns it off.
const INTERVALS: [string, number][] = [
  ['Off', 0],
  ['10s', 10],
  ['30s', 30],
  ['1m', 60],
  ['5m', 300],
  ['15m', 900],
  ['30m', 1800],
  ['1h', 3600],
]

type TopicState = 'empty' | 'lagging' | 'ok' | 'unowned'

const DOT: Record<TopicState, string> = {
  empty: 'var(--ds-border-secondary)',
  lagging: 'var(--ds-text-warning)',
  ok: 'var(--ds-text-success)',
  unowned: 'var(--ds-text-danger)',
}

export function IggyTopicsCard() {
  const [interval, setInterval] = useState(30)
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [dir, setDir] = useState(1)
  const { data, isError, isFetching, isLoading, refetch } = useQuery({
    queryFn: ({ signal }) => getDashboardIggy(signal),
    queryKey: ['admin-overview', 'iggy'],
    refetchInterval: interval ? interval * 1000 : false,
    staleTime: 5_000,
  })

  const topics = useMemo(() => data?.topics ?? [], [data])
  const rows = useMemo(
    () => sortTopics(topics, sortKey, dir),
    [topics, sortKey, dir],
  )
  const unowned = topics.filter((t) => topicState(t) === 'unowned').length
  const lagging = topics.filter((t) => topicState(t) === 'lagging').length
  const streams = new Set(topics.map((t) => t.stream)).size
  const total = topics.reduce((sum, t) => sum + t.messages, 0)

  const sort = (key: SortKey) => {
    setDir(sortKey === key ? -dir : key === 'name' ? 1 : -1)
    setSortKey(key)
  }

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-tertiary flex flex-wrap items-center gap-3 border-b px-5 py-3.5">
        <span className="bg-success text-success flex size-7 items-center justify-center rounded-md">
          <Waypoints className="size-3.75" />
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="text-[15px] font-semibold">Iggy topics</span>
          <span className="text-secondary font-mono text-xs">
            {data
              ? `${streams} ${streams === 1 ? 'stream' : 'streams'} · ${topics.length} ${topics.length === 1 ? 'topic' : 'topics'} · ${total.toLocaleString('en-US')} messages`
              : isError
                ? 'unavailable'
                : 'checking…'}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-4">
          {data && (
            <Badge
              variant={unowned ? 'danger' : lagging ? 'warning' : 'success'}
            >
              {unowned
                ? `${unowned} unowned`
                : lagging
                  ? `${lagging} lagging`
                  : 'All topics owned'}
            </Badge>
          )}
          <div className="border-secondary bg-primary flex h-7.5 items-stretch rounded-md border">
            <button
              aria-label="Refresh now"
              className="text-secondary hover:bg-secondary hover:text-primary flex w-8 items-center justify-center rounded-l-[5px]"
              onClick={() => void refetch()}
              title="Refresh now"
              type="button"
            >
              <RefreshCw
                className={`size-3.75 ${isFetching ? 'animate-spin' : ''}`}
              />
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="border-secondary text-secondary hover:bg-secondary hover:text-primary flex min-w-13 items-center justify-between gap-1 rounded-r-[5px] border-l px-2 text-xs tabular-nums"
                title="Auto-refresh interval"
              >
                <span>
                  {INTERVALS.find(([, sec]) => sec === interval)?.[0]}
                </span>
                <ChevronDown className="size-3" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-30">
                <DropdownMenuLabel className="text-tertiary text-[11px] tracking-wider uppercase">
                  Auto-refresh
                </DropdownMenuLabel>
                <DropdownMenuRadioGroup
                  onValueChange={(value) => setInterval(Number(value))}
                  value={String(interval)}
                >
                  {INTERVALS.map(([label, sec]) => (
                    <DropdownMenuRadioItem key={sec} value={String(sec)}>
                      {label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full caption-bottom text-sm">
          <thead className="[&_tr]:border-b">
            <tr className="border-b">
              {COLUMNS.map((c) => (
                <th
                  aria-sort={
                    sortKey === c.key
                      ? dir > 0
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                  className={`text-muted-foreground h-9 cursor-pointer px-4 align-middle text-[11px] font-medium tracking-wider whitespace-nowrap uppercase select-none ${c.align === 'right' ? 'text-right' : 'text-left'}`}
                  key={c.key}
                  onClick={() => sort(c.key)}
                >
                  {c.label}
                  {sortKey === c.key ? (dir > 0 ? ' ↑' : ' ↓') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="[&_tr:last-child]:border-0">
            {isLoading
              ? [0, 1, 2, 3].map((i) => (
                  <tr aria-busy className="border-b" key={i}>
                    <td className="px-4 py-1.5" colSpan={COLUMNS.length}>
                      <Sk h={13} />
                    </td>
                  </tr>
                ))
              : rows.map((t, i) => (
                  <TopicRow
                    key={`${t.stream}/${t.topic}`}
                    repeatStream={
                      sortKey === 'name' &&
                      i > 0 &&
                      rows[i - 1].stream === t.stream
                    }
                    topic={t}
                  />
                ))}
          </tbody>
        </table>
        {isError && !data && (
          <p className="text-danger px-5 py-3 text-sm">Unavailable</p>
        )}
      </div>
      <div className="border-tertiary text-tertiary flex flex-wrap gap-4 border-t px-5 py-2.5 text-xs">
        <Legend color={DOT.ok} label="Owned" />
        <Legend color={DOT.lagging} label="Lagging" />
        <Legend color={DOT.unowned} label="Unowned" />
        <Legend color={DOT.empty} label="Empty" />
        <span className="ml-auto">Click a column to sort</span>
      </div>
    </Card>
  )
}

function fmt(value: null | number | undefined): string {
  return value == null ? '—' : value.toLocaleString('en-US')
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="size-1.75 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
}

function sortTopics(
  topics: IggyTopic[],
  key: SortKey,
  dir: number,
): IggyTopic[] {
  const name = (t: IggyTopic) => `${t.stream}/${t.topic}`
  const value = (t: IggyTopic): number | string =>
    key === 'name' ? name(t) : (t[key] ?? -1)
  return [...topics].sort((a, b) => {
    const x = value(a)
    const y = value(b)
    const order = (x > y ? 1 : x < y ? -1 : 0) * dir
    return order || name(a).localeCompare(name(b))
  })
}

// fallow-ignore-next-line complexity
function TopicRow({
  repeatStream,
  topic: t,
}: {
  repeatStream: boolean
  topic: IggyTopic
}) {
  const state = topicState(t)
  const muted = t.messages === 0
  const cell =
    'px-4 py-1.5 align-middle text-right font-mono text-[13px] tabular-nums'
  return (
    <tr className="hover:bg-muted/50 border-b transition-colors">
      <td className="px-4 py-1.5 align-middle">
        <div className="flex items-center gap-2.5 font-mono text-[13px] whitespace-nowrap">
          <span
            className="size-1.75 flex-none rounded-full"
            style={{ background: DOT[state] }}
          />
          <span>
            <span
              className="text-tertiary"
              style={{ opacity: repeatStream ? 0.35 : 1 }}
            >
              {t.stream}/
            </span>
            <span className={muted ? 'text-tertiary' : 'text-primary'}>
              {t.topic}
            </span>
          </span>
        </div>
      </td>
      <td className={`${cell} ${muted ? 'text-tertiary' : 'text-primary'}`}>
        {fmt(t.messages)}
      </td>
      <td className={`${cell} text-secondary`}>{fmt(t.current_offset)}</td>
      <td className={`${cell} text-tertiary`}>{fmt(t.stored_offset)}</td>
      <td
        className={`${cell} ${state === 'lagging' ? 'text-warning' : 'text-tertiary'}`}
      >
        {fmt(t.lag)}
      </td>
      <td className={cell}>{t.members}</td>
      <td
        className={`${cell} ${state === 'unowned' ? 'text-danger' : 'text-primary'}`}
      >
        {t.members_owning}
      </td>
    </tr>
  )
}

function topicState(t: IggyTopic): TopicState {
  // Each topic has a sink group. No members while messages wait means
  // the sink is down.
  if (t.members === 0 && t.messages > 0) return 'unowned'
  if (t.members_owning < t.members) return 'unowned'
  if ((t.lag ?? 0) > 0) return 'lagging'
  if (t.messages === 0) return 'empty'
  return 'ok'
}
