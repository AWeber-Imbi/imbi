/** The family of a tool, which picks its tag color and its readable view. */
export type Family = 'agent' | 'edit' | 'mcp' | 'read' | 'shell'

/** The tag colors of each tool family. */
export const FAMILY_TAG: Record<Family, string> = {
  agent: 'bg-accent text-accent',
  edit: 'bg-teal text-teal',
  mcp: 'bg-accent text-accent',
  read: 'bg-info text-info',
  shell: 'bg-secondary text-primary',
}

/** Lines of output shown before "Show all". */
export const OUTPUT_LINES = 40

export function familyOf(tool: string): Family {
  if (tool === 'Bash') return 'shell'
  if (['Edit', 'MultiEdit', 'NotebookEdit', 'Write'].includes(tool))
    return 'edit'
  if (tool === 'Task' || tool === 'Agent') return 'agent'
  if (tool.startsWith('mcp__')) return 'mcp'
  return 'read'
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** A string as is; anything else as JSON. */
export function label(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** `Bash`, `Edit`, `github · get_pr`, `Subagent`. */
export function toolLabel(tool: string): string {
  if (tool.startsWith('mcp__')) {
    const [, server, ...name] = tool.split('__')
    return `${server} · ${name.join('__')}`
  }
  if (tool === 'Task' || tool === 'Agent') return 'Subagent'
  return tool
}

/** The one-line summary of a call's arguments. */
export function toolSummary(tool: string, args: unknown): string {
  const a = (args ?? {}) as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  switch (tool) {
    case 'Agent':
    case 'Task':
      return [str(a.subagent_type), str(a.description)]
        .filter(Boolean)
        .join(' · ')
    case 'Bash':
      return str(a.command)
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
    case 'Read':
    case 'Write':
      return str(a.file_path) || str(a.notebook_path)
    case 'Glob':
    case 'Grep':
      return [str(a.pattern), str(a.path)].filter(Boolean).join('  in ')
    case 'WebFetch':
      return str(a.url)
    case 'WebSearch':
      return str(a.query)
  }
  const first = Object.values(a).find((v) => typeof v === 'string')
  return typeof first === 'string' ? first : JSON.stringify(a)
}
