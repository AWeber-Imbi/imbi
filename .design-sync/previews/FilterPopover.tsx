import { type ReactNode, useEffect, useRef, useState } from 'react'

import { FilterPopover } from 'imbi-ui'

const SCORE_OPTIONS = [
  { count: 42, dotClass: 'bg-success', label: 'Healthy 85–100', slug: 'healthy' },
  { count: 17, dotClass: 'bg-warning', label: 'Fair 75–84', slug: 'fair' },
  { count: 6, dotClass: 'bg-danger', label: 'At risk 50–74', slug: 'at-risk' },
  { count: 0, dotClass: 'bg-muted-foreground', label: 'Unscored', slug: 'unscored' },
]

const DRIFT_OPTIONS = [
  { count: 11, label: 'staging → production', slug: 'staging-production' },
  { count: 4, label: 'testing → staging', slug: 'testing-staging' },
]

const TYPE_OPTIONS = [
  { count: 38, label: 'HTTP API', slug: 'http-api' },
  { count: 21, label: 'Consumer', slug: 'consumer' },
  { count: 9, label: 'Scheduled Job', slug: 'scheduled-job' },
  { count: 14, label: 'Python Library', slug: 'python-library' },
]

// FilterPopover keeps its open state internally; click the trigger once
// on mount so the card shows the open checkbox list, then drop the
// auto-focus ring so the list reads at rest.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('button')?.click()
    const id = requestAnimationFrame(() =>
      (document.activeElement as HTMLElement | null)?.blur(),
    )
    return () => cancelAnimationFrame(id)
  }, [])
  return <div ref={ref}>{children}</div>
}

const useToggleSet = (initial: string[]) => {
  const [active, setActive] = useState(() => new Set(initial))
  const toggle = (slug: string) =>
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  return { active, clear: () => setActive(new Set()), toggle }
}

export const ButtonOpen = () => {
  const { active, clear, toggle } = useToggleSet(['http-api', 'consumer'])
  return (
    <PreviewOnlyAutoOpen>
      <FilterPopover
        activeFilters={active}
        label="Project type"
        onClear={clear}
        onToggle={toggle}
        options={TYPE_OPTIONS}
        variant="button"
      />
    </PreviewOnlyAutoOpen>
  )
}

export const TableHeaderIconOpen = () => {
  const { active, toggle } = useToggleSet(['at-risk'])
  return (
    <PreviewOnlyAutoOpen>
      <FilterPopover
        activeFilters={active}
        label="health score"
        onToggle={toggle}
        options={SCORE_OPTIONS}
      />
    </PreviewOnlyAutoOpen>
  )
}

export const FilterBarClosed = () => {
  const types = useToggleSet(['http-api'])
  const scores = useToggleSet([])
  return (
    <div className="flex items-center gap-2">
      <FilterPopover
        activeFilters={types.active}
        label="Project type"
        onClear={types.clear}
        onToggle={types.toggle}
        options={TYPE_OPTIONS}
        variant="button"
      />
      <FilterPopover
        activeFilters={scores.active}
        label="Health score"
        onClear={scores.clear}
        onToggle={scores.toggle}
        options={SCORE_OPTIONS}
        variant="button"
      />
    </div>
  )
}

export const TableHeaderClosed = () => {
  const drift = useToggleSet([])
  const score = useToggleSet(['healthy', 'fair'])
  return (
    <div className="text-secondary flex items-center gap-6 text-xs font-medium tracking-wide uppercase">
      <span className="flex items-center gap-1.5">
        Drift
        <FilterPopover
          activeFilters={drift.active}
          label="drift"
          onToggle={drift.toggle}
          options={DRIFT_OPTIONS}
        />
      </span>
      <span className="flex items-center gap-1.5">
        Score
        <FilterPopover
          activeFilters={score.active}
          label="health score"
          onToggle={score.toggle}
          options={SCORE_OPTIONS}
        />
      </span>
    </div>
  )
}
