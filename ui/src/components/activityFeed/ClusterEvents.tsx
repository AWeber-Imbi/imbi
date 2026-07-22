import { RelativeTime } from '@/components/ui/RelativeTime'
import type { ActivityFeedEntry } from '@/types'

import {
  entryEventLabel,
  entryTimeIso,
  entryTone,
  entryVerb,
} from './entryAdapters'
import { StatusChip } from './StatusChip'
import { toneStyle } from './tone'

interface ClusterEventsProps {
  /** Left indent (px) so rows align under the group content, not the rail. */
  indent?: number
  /** Cluster members to list, newest-first. */
  items: ActivityFeedEntry[]
}

/** The expanded body of a group: one compact row per underlying event. */
export function ClusterEvents({ indent = 38, items }: ClusterEventsProps) {
  return (
    <ul className="mt-2.5 flex flex-col gap-px" style={{ marginLeft: indent }}>
      {items.map((item, i) => {
        const tone = entryTone(item)
        return (
          <li
            className="hover:bg-secondary grid grid-cols-[14px_1fr_auto] items-center gap-x-2.5 rounded-md px-2.5 py-1.5"
            key={`${entryVerb(item)}-${entryTimeIso(item) ?? ''}-${i}`}
          >
            <span
              className="size-1.75 rounded-full"
              style={{ background: toneStyle(tone).dotVar }}
            />
            <span className="text-primary truncate font-mono text-xs">
              {entryEventLabel(item)}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <StatusChip label={entryVerb(item)} tone={tone} />
              <RelativeTime
                className="text-tertiary font-mono text-[11px]"
                tooltip={false}
                value={entryTimeIso(item)}
                variant="narrow"
              />
            </span>
          </li>
        )
      })}
    </ul>
  )
}
