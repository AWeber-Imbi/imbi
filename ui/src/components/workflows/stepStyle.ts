import {
  Bot,
  Clock,
  type LucideIcon,
  Mail,
  Play,
  Rocket,
  RotateCcw,
  Sparkles,
  SquareFunction,
  Timer,
  Webhook,
} from 'lucide-react'

import type { StepCategory } from './types'

const ICONS: Record<string, LucideIcon> = {
  deploy: Rocket,
  email: Mail,
  manual: Play,
  model_decision: Sparkles,
  rollback: RotateCcw,
  schedule: Clock,
  wait: Timer,
  webhook: Webhook,
}

// Category tiles follow the mockup (agent purple, logic blue, action
// green), which matches design.md's knowledge-graph node colours. The
// mockup's amber trigger tile is gray here: design.md keeps amber for
// the brand, primary actions, and warnings.
export const CATEGORY_TILE: Record<StepCategory, string> = {
  action: 'bg-success text-success',
  agent: 'bg-accent text-accent',
  logic: 'bg-info text-info',
  trigger: 'bg-tertiary text-secondary',
}

export const CATEGORY_LABEL: Record<StepCategory, string> = {
  action: 'Actions',
  agent: 'Agents',
  logic: 'Logic',
  trigger: 'Triggers',
}

export const CATEGORY_ORDER: StepCategory[] = [
  'trigger',
  'agent',
  'logic',
  'action',
]

export function stepIcon(type: string, category?: StepCategory): LucideIcon {
  return ICONS[type] ?? (category === 'agent' ? Bot : SquareFunction)
}
