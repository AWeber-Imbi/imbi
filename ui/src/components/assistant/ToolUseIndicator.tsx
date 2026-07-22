import { Sparkles } from 'lucide-react'

import { Sk } from '@/components/ui/skeleton'

interface ToolUseIndicatorProps {
  toolName: string
}

const TOOL_FRIENDLY_NAMES: Record<string, string> = {
  get_project: 'Looking up project details',
  list_blueprints: 'Fetching blueprints',
  list_projects: 'Searching projects',
  list_teams: 'Loading teams',
  list_users: 'Looking up users',
  navigate_to: 'Navigating',
  refresh_data: 'Refreshing data',
}

export function ToolUseIndicator({ toolName }: ToolUseIndicatorProps) {
  const friendlyName = TOOL_FRIENDLY_NAMES[toolName] ?? `Running ${toolName}`

  return (
    <div className="flex flex-col gap-1.5 py-1 pl-4">
      <div className="text-amber-text flex items-center gap-2 font-mono text-xs">
        <Sparkles className="size-3" />
        <span>{friendlyName}…</span>
      </div>
      <Sk ai line w="60%" />
    </div>
  )
}
