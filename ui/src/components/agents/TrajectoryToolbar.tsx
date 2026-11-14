import { useCallback, useState } from 'react'

import { Search } from 'lucide-react'

import { cn } from '@/lib/utils'

import type { FoldButton } from './trajectoryModel'

export const DURATION_KEY = 'dsh.trajectory.duration'

const FOLDS: { key: FoldButton; label: string; noun: string }[] = [
  { key: 'turns', label: 'Turns', noun: 'turns' },
  { key: 'calls', label: 'Calls', noun: 'calls' },
  { key: 'subcalls', label: 'Subcalls', noun: 'subcalls' },
]

const BUTTON =
  'inline-flex h-7 shrink-0 items-center gap-1 rounded-lg text-(--tj-label-2) transition-colors outline-none hover:bg-(--tj-hover) hover:text-(--tj-label-1) focus-visible:shadow-[0_0_0_2px_var(--tj-business)] disabled:cursor-default disabled:text-(--tj-label-3) disabled:hover:bg-transparent'

/** The toolbar: Duration, the three fold buttons, and search. */
export function TrajectoryToolbar({
  duration,
  folded,
  onDuration,
  onFold,
  onQuery,
  query,
}: {
  duration: boolean
  /** Per fold button: whether everything it folds is folded, or null if nothing can fold. */
  folded: Record<FoldButton, boolean | null>
  onDuration: (on: boolean) => void
  onFold: (button: FoldButton) => void
  onQuery: (query: string) => void
  query: string
}) {
  return (
    <div
      className="hairline-b sticky top-0 z-4 flex min-h-10 shrink-0 flex-wrap items-center gap-1 border-(--tj-border-2) bg-(--tj-bg-1) px-2 py-1.5 text-[13px] leading-[18px]"
      role="toolbar"
    >
      <button
        aria-pressed={duration}
        className={cn(
          BUTTON,
          'px-2',
          duration && 'bg-(--tj-hover) text-(--tj-label-1)',
        )}
        onClick={() => onDuration(!duration)}
        title={duration ? 'Use equal-width operations' : 'Use actual duration'}
        type="button"
      >
        <svg aria-hidden fill="none" height="12" viewBox="0 0 16 16" width="12">
          <circle
            cx="8"
            cy="8"
            r="5.25"
            stroke="currentColor"
            strokeWidth="1.25"
          />
          <path
            d="M8 4.75V8l2.25 1.5"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.25"
          />
        </svg>
        Duration
      </button>
      {FOLDS.map(({ key, label, noun }) => {
        const all = folded[key]
        const action =
          all === null
            ? `No ${noun} to fold`
            : all
              ? `Expand ${noun}`
              : `Collapse ${noun}`
        return (
          <button
            aria-label={action}
            className={cn(BUTTON, 'px-2')}
            disabled={all === null}
            key={key}
            onClick={() => onFold(key)}
            title={action}
            type="button"
          >
            <span
              aria-hidden
              className="font-tj-code text-[14px] leading-none text-(--tj-label-3)"
            >
              {all ? '⊞' : '⊟'}
            </span>
            {label}
          </button>
        )
      })}
      <label className="hairline ml-auto flex h-7 min-w-21 flex-[0_1_164px] items-center gap-1 rounded-lg border-(--tj-border-4) bg-(--tj-bg-2) px-1.5 text-(--tj-label-3) transition-colors focus-within:border-(--tj-business) focus-within:bg-(--tj-bg-1) hover:border-(--tj-caption)">
        <Search aria-hidden className="size-tab-y shrink-0" />
        <input
          aria-label="Search trajectory"
          className="min-w-0 flex-1 bg-transparent text-[13px] text-(--tj-label-1) outline-none placeholder:text-(--tj-caption)"
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search"
          type="search"
          value={query}
        />
      </label>
    </div>
  )
}

/** The Duration toggle, kept per browser; off by default. */
export function useTrajectoryDuration(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return window.localStorage.getItem(DURATION_KEY) === 'true'
    } catch {
      return false
    }
  })
  const update = useCallback((next: boolean) => {
    setOn(next)
    try {
      window.localStorage.setItem(DURATION_KEY, String(next))
    } catch {
      // Storage can be full or blocked; the toggle still applies to this page.
    }
  }, [])
  return [on, update]
}
