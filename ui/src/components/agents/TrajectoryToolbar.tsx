import { type ReactNode, useCallback, useState } from 'react'

import { Bot, MessagesSquare, Timer, Wrench } from 'lucide-react'

import { ButtonGroup } from '@/components/ui/button-group'
import { storage } from '@/lib/storage'

import { ToolbarSearch } from './taskSearch'
import { TaskToolbar, ToolbarToggle } from './TaskToolbar'
import type { FoldButton } from './trajectoryModel'

export const DURATION_KEY = 'dsh.trajectory.duration'

const FOLDS: {
  icon: typeof Timer
  key: FoldButton
  none: string
  noun: string
}[] = [
  {
    icon: MessagesSquare,
    key: 'turns',
    none: 'This task has no turns yet.',
    noun: 'turns',
  },
  {
    icon: Wrench,
    key: 'calls',
    none: 'No turn in this task made a tool call.',
    noun: 'tool calls',
  },
  {
    icon: Bot,
    key: 'subcalls',
    none: 'No subagent ran in this task.',
    noun: 'subagent calls',
  },
]

/** The toolbar: Duration, the three fold buttons, search, and copy. */
export function TrajectoryToolbar({
  duration,
  end,
  folded,
  onDuration,
  onFold,
  onQuery,
  query,
}: {
  duration: boolean
  end?: ReactNode
  /** Per fold button: whether everything it folds is folded, or null if nothing can fold. */
  folded: Record<FoldButton, boolean | null>
  onDuration: (on: boolean) => void
  onFold: (button: FoldButton) => void
  onQuery: (query: string) => void
  query: string
}) {
  return (
    <TaskToolbar label="Trajectory">
      <ToolbarToggle
        hint={duration ? 'Use equal-width operations' : 'Use actual duration'}
        icon={Timer}
        label="Duration"
        onPressedChange={onDuration}
        pressed={duration}
      />
      <ButtonGroup aria-label="Fold">
        {FOLDS.map(({ icon, key, none, noun }) => {
          const all = folded[key]
          const action = all ? `Expand ${noun}` : `Collapse ${noun}`
          return (
            <ToolbarToggle
              disabled={all === null ? none : undefined}
              icon={icon}
              key={key}
              label={action}
              onPressedChange={() => onFold(key)}
              pressed={all === true}
            />
          )
        })}
      </ButtonGroup>
      <div className="ml-auto flex min-w-40 flex-1 items-center justify-end gap-2">
        <ToolbarSearch
          label="Search trajectory"
          onChange={onQuery}
          value={query}
        />
        {end}
      </div>
    </TaskToolbar>
  )
}

/** The Duration toggle, kept per browser; off by default. */
export function useTrajectoryDuration(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => storage.getItem(DURATION_KEY) === 'true')
  const update = useCallback((next: boolean) => {
    setOn(next)
    storage.setItem(DURATION_KEY, String(next))
  }, [])
  return [on, update]
}
