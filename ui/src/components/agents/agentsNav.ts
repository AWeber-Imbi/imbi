import {
  Bot,
  ChartColumn,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Server,
  SlidersHorizontal,
  Waypoints,
  Workflow,
} from 'lucide-react'

import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { hasPermission } from '@/hooks/useHasPermission'

// The pages of the Agents area. The header menu and the area sidebar
// both use this list, so they always agree.

export interface AgentsNavItem {
  /** Only platform administrators (`is_admin`) see the page. */
  adminOnly?: boolean
  group: 'Agentic platform' | 'Settings'
  icon: LucideIcon
  id: AgentsSection
  label: string
  note: string
  /** An organization permission that also shows the page. */
  permission?: string
}

export type AgentsSection =
  | 'dashboard'
  | 'egress'
  | 'manage'
  | 'platform'
  | 'runners'
  | 'tasks'
  | 'usage'
  | 'workflows'

export const AGENTS_BASE_PATH = '/agents'

const AGENTS_NAV: AgentsNavItem[] = [
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
  {
    group: 'Settings',
    icon: SlidersHorizontal,
    id: 'platform',
    label: 'Platform',
    note: 'Base configuration and plugin marketplaces',
  },
  {
    group: 'Settings',
    icon: Server,
    id: 'runners',
    label: 'Runners',
    note: 'Runner pools that serve the organization',
    permission: 'harness_pool:read',
  },
  {
    adminOnly: true,
    group: 'Settings',
    icon: Waypoints,
    id: 'egress',
    label: 'Egress Destinations',
    note: 'Internal networks that runner pods may reach',
  },
]

export function agentsPath(section: AgentsSection, ...rest: string[]): string {
  return [AGENTS_BASE_PATH, section, ...rest.map(encodeURIComponent)].join('/')
}

/** The {@link AGENTS_NAV} pages that the current user can open. */
export function useAgentsNav(): AgentsNavItem[] {
  const { user } = useAuth()
  const { selectedOrganization } = useOrganization()
  const isAdmin = user?.is_admin === true
  return AGENTS_NAV.filter((item) => {
    if (item.adminOnly) return isAdmin
    if (!item.permission) return true
    // The API admits a platform administrator without membership.
    return (
      isAdmin ||
      hasPermission(user, item.permission, selectedOrganization?.slug)
    )
  })
}
