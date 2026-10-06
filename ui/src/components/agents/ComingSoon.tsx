import { Badge } from '@/components/ui/badge'

import { AGENTS_NAV, type AgentsSection } from './agentsNav'

// Agents can be defined, but nothing runs them yet. These pages say so
// instead of showing sample data.
const COPY: Record<Exclude<AgentsSection, 'manage'>, string> = {
  dashboard:
    'The agent dashboard is not built yet. When agents can run, it will show their activity, the tasks that need you, and their spend.',
  tasks:
    'Agents do not run yet, so there are no tasks. When agents can run, their tasks and the tasks that wait for you will show here.',
  usage:
    'Agents do not run yet, so there is no usage. When agents can run, their token use and cost will show here.',
  workflows:
    'Workflows are not built yet. A workflow will connect agents into a run with more than one step.',
}

export function ComingSoon({
  section,
}: {
  section: Exclude<AgentsSection, 'manage'>
}) {
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
