import { Badge } from '@/components/ui/badge'

import { AGENTS_NAV, type AgentsSection } from './agentsNav'

// The pages of the Agents area that are not built yet. They say so
// instead of showing sample data.
type Section = Exclude<
  AgentsSection,
  'dashboard' | 'manage' | 'tasks' | 'usage'
>

const COPY: Record<Section, string> = {
  workflows:
    'Workflows are not built yet. A workflow will connect agents into a run with more than one step.',
}

export function ComingSoon({ section }: { section: Section }) {
  const item = AGENTS_NAV.find((n) => n.id === section)
  const Icon = item?.icon
  return (
    <div className="flex flex-col gap-6 p-8">
      <div className="border-border bg-card flex flex-col items-center gap-3 rounded-lg border px-6 py-16 text-center">
        {Icon && <Icon className="text-tertiary size-8" />}
        <div className="flex items-center gap-2">
          <h2 className="text-h2">{item?.label}</h2>
          <Badge variant="neutral">Coming soon</Badge>
        </div>
        <p className="text-secondary max-w-lg text-sm">{COPY[section]}</p>
      </div>
    </div>
  )
}
