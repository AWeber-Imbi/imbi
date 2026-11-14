import { ChartColumn, ChartGantt, MessageSquareText } from 'lucide-react'

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

import { TOOLBAR_ITEM } from './TaskToolbar'

export type ActivityView = 'conversation' | 'statistics' | 'trajectory'

const VIEWS: {
  icon: typeof ChartColumn
  label: string
  value: ActivityView
}[] = [
  { icon: MessageSquareText, label: 'Conversation', value: 'conversation' },
  { icon: ChartGantt, label: 'Trajectory', value: 'trajectory' },
  { icon: ChartColumn, label: 'Statistics', value: 'statistics' },
]

/** Switches between the three views of a task's activity. */
export function ActivityViewSwitch({
  onChange,
  value,
}: {
  onChange: (view: ActivityView) => void
  value: ActivityView
}) {
  return (
    <ToggleGroup
      aria-label="View"
      onValueChange={(v) => {
        if (isActivityView(v)) onChange(v)
      }}
      spacing={0}
      type="single"
      value={value}
      variant="outline"
    >
      {VIEWS.map(({ icon: Icon, label, value: v }) => (
        <ToggleGroupItem className={TOOLBAR_ITEM} key={v} value={v}>
          <Icon />
          {label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

export function isActivityView(value: unknown): value is ActivityView {
  return VIEWS.some((v) => v.value === value)
}
