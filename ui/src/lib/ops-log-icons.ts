import {
  ArrowRightLeft,
  ArrowUp,
  type LucideIcon,
  PackagePlus,
  Rocket,
  RotateCw,
  Scale,
  SlidersHorizontal,
  Trash2,
  Undo2,
} from 'lucide-react'

import type { OperationsLogEntryType } from '@/types'

export const ENTRY_TYPE_ICONS: Record<OperationsLogEntryType, LucideIcon> = {
  Configured: SlidersHorizontal,
  Decommissioned: Trash2,
  Deployed: Rocket,
  Migrated: ArrowRightLeft,
  Provisioned: PackagePlus,
  Restarted: RotateCw,
  'Rolled Back': Undo2,
  Scaled: Scale,
  Upgraded: ArrowUp,
}
