import { Badge } from '@/components/ui/badge'

import type { WorkflowStatus } from './types'

const VARIANT = {
  active: 'success',
  draft: 'info',
  paused: 'neutral',
} as const

const LABEL: Record<WorkflowStatus, string> = {
  active: 'Active',
  draft: 'Draft',
  paused: 'Paused',
}

export function StatusBadge({ status }: { status: WorkflowStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>
}
