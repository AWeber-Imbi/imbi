import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { MCPServer, MCPServerStatus } from '@/types'

// The list/detail pill folds `enabled` into the runtime status: a disabled
// server reads as "Disabled" regardless of its last health check.
type EffectiveStatus = 'disabled' | MCPServerStatus

const STATUS_META: Record<
  EffectiveStatus,
  { label: string; variant: BadgeProps['variant'] }
> = {
  degraded: { label: 'Degraded', variant: 'warning' },
  disabled: { label: 'Disabled', variant: 'neutral' },
  healthy: { label: 'Healthy', variant: 'success' },
  unknown: { label: 'Not tested', variant: 'neutral' },
  unreachable: { label: 'Unreachable', variant: 'danger' },
}

export function McpServerStatusPill({ server }: { server: MCPServer }) {
  const meta = STATUS_META[effectiveStatus(server)]
  return (
    <Badge className="gap-1.5" variant={meta.variant}>
      <span className="size-1.5 rounded-full bg-current" />
      {meta.label}
    </Badge>
  )
}

function effectiveStatus(server: MCPServer): EffectiveStatus {
  return server.enabled ? server.status : 'disabled'
}
