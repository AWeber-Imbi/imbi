import { Loader2 } from 'lucide-react'

interface ToolUseIndicatorProps {
  toolName: string
  isDarkMode: boolean
}

const TOOL_FRIENDLY_NAMES: Record<string, string> = {
  list_projects: 'Searching projects',
  get_project: 'Looking up project details',
  list_blueprints: 'Fetching blueprints',
  list_teams: 'Loading teams',
  list_users: 'Looking up users',
}

export function ToolUseIndicator({
  toolName,
  isDarkMode,
}: ToolUseIndicatorProps) {
  const friendlyName =
    TOOL_FRIENDLY_NAMES[toolName] ?? `Running ${toolName}`

  return (
    <div
      className={`flex items-center gap-2 pl-4 py-1 text-xs font-mono ${
        isDarkMode ? 'text-yellow-500/70' : 'text-amber-600/70'
      }`}
    >
      <Loader2 className="w-3 h-3 animate-spin" />
      <span>{friendlyName}...</span>
    </div>
  )
}
