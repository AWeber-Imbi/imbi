const TOOL_FRIENDLY_NAMES: Record<string, string> = {
  get_project: 'Looking up project details',
  list_blueprints: 'Fetching blueprints',
  list_projects: 'Searching projects',
  list_teams: 'Loading teams',
  list_users: 'Looking up users',
  navigate_to: 'Navigating',
  refresh_data: 'Refreshing data',
}

/** A readable label for a tool call. */
export function toolLabel(toolName: string): string {
  return TOOL_FRIENDLY_NAMES[toolName] ?? `Running ${toolName}`
}
