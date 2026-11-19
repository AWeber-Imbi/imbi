import {
  Bot,
  BrainCircuit,
  Clock,
  Code,
  type LucideIcon,
  Mail,
  MessageSquare,
  Play,
  Rocket,
  RotateCcw,
  Sparkles,
  Split,
  SquareFunction,
  Timer,
  Webhook,
} from 'lucide-react'

import type { StepCategory } from './types'

const ICONS: Record<string, LucideIcon> = {
  agent: Bot,
  condition: Split,
  deploy: Rocket,
  email: Mail,
  llm_call: BrainCircuit,
  manual: Play,
  model_decision: Sparkles,
  rollback: RotateCcw,
  schedule: Clock,
  script: Code,
  slack: MessageSquare,
  wait: Timer,
  webhook: Webhook,
}

// Category tiles follow the mockup (logic blue, action green), which matches design.md's knowledge-graph node colours. The
// mockup's amber trigger tile is gray here: design.md keeps amber for
// the brand, primary actions, and warnings.
export const CATEGORY_TILE: Record<StepCategory, string> = {
  action: 'bg-success text-success',
  logic: 'bg-info text-info',
  trigger: 'bg-tertiary text-secondary',
}

export const CATEGORY_LABEL: Record<StepCategory, string> = {
  action: 'Actions',
  logic: 'Logic',
  trigger: 'Triggers',
}

export const CATEGORY_ORDER: StepCategory[] = ['trigger', 'logic', 'action']

export function stepIcon(type: string): LucideIcon {
  return ICONS[type] ?? SquareFunction
}
