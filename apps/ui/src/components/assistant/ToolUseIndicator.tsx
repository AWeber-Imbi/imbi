import { Loader2 } from 'lucide-react'

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
    <div className="text-warning/70 flex items-center gap-2 py-1 pl-4 font-mono text-xs">
      <Loader2 className="h-3 w-3 animate-spin" />
      <span>{friendlyName}...</span>
    </div>
  )
}
