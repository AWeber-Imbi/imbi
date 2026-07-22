import type { LucideIcon } from 'lucide-react'

import type { OperationsLogRecord } from '@/types'

export interface PluginOpsLogContext {
  action?: string
  entry: OperationsLogRecord
  payload: Record<string, unknown>
}

export interface PluginOpsLogRenderer {
  // Expanded panel content (rendered above Notes / Link in the details view).
  details?(ctx: PluginOpsLogContext): React.ReactNode
  // Human-readable name surfaced as the details section heading.
  displayName: string
  // Optional plugin-branded icon override for the stream row.
  icon?: LucideIcon
  // Compact one-liner shown under the row title.
  label?(ctx: PluginOpsLogContext): string
}
