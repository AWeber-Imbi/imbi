import {
  Bot,
  ChartColumn,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Workflow,
} from 'lucide-react'

// The pages of the Agents area. The header menu and the area sidebar
// both use this list, so they always agree.

export interface AgentsNavItem {
  group: 'Agentic platform' | 'Settings'
  icon: LucideIcon
  id: AgentsSection
  label: string
  note: string
}

export type AgentsSection =
  | 'dashboard'
  | 'manage'
  | 'tasks'
  | 'usage'
  | 'workflows'

export const AGENTS_BASE_PATH = '/agents'

export const AGENTS_NAV: AgentsNavItem[] = [
  {
    group: 'Agentic platform',
    icon: LayoutDashboard,
    id: 'dashboard',
    label: 'Dashboard',
    note: 'Agent activity at a glance',
  },
  {
    group: 'Agentic platform',
    icon: Inbox,
    id: 'tasks',
    label: 'Tasks',
    note: 'Work that agents do',
  },
  {
    group: 'Agentic platform',
    icon: ChartColumn,
    id: 'usage',
    label: 'Usage',
    note: 'Tokens and spend',
  },
  {
    group: 'Settings',
    icon: Bot,
    id: 'manage',
    label: 'Agents',
    note: 'Define and configure agents',
  },
  {
    group: 'Settings',
    icon: Workflow,
    id: 'workflows',
    label: 'Workflows',
    note: 'Multi-step runs built from agents',
  },
]

export function agentsPath(section: AgentsSection, ...rest: string[]): string {
  return [AGENTS_BASE_PATH, section, ...rest.map(encodeURIComponent)].join('/')
}

export function isAgentsSection(value?: string): value is AgentsSection {
  return AGENTS_NAV.some((item) => item.id === value)
}
