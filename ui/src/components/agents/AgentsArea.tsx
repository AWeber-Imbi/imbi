import { useEffect, useState } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'

import { AgentRunners } from '@/components/admin/AgentRunners'
import { EgressDestinationManagement } from '@/components/admin/EgressDestinationManagement'
import { WorkflowsManagement } from '@/components/workflows/WorkflowsManagement'
import { useOrganization } from '@/contexts/OrganizationContext'
import { cn } from '@/lib/utils'

import { useAgentList } from './agentQueries'
import { AgentsManagement } from './AgentsManagement'
import {
  type AgentsNavItem,
  agentsPath,
  type AgentsSection,
  useAgentsNav,
} from './agentsNav'
import { DashboardPage } from './DashboardPage'
import { PlatformPage } from './PlatformPage'
import { useWaitingTaskCount } from './taskQueries'
import { TasksPage } from './TasksPage'
import { UsagePage } from './UsagePage'

/**
 * The Agents area: its own sidebar (Agentic platform, Settings) and the
 * page for the section in the URL.
 */
export function AgentsArea() {
  const { section } = useParams<{ section?: string }>()
  const navigate = useNavigate()
  const items = useAgentsNav()
  // A page the user cannot open is the same as an unknown page.
  const visible = items.some((item) => item.id === section)
  const current: AgentsSection = visible
    ? (section as AgentsSection)
    : 'dashboard'

  useEffect(() => {
    if (!visible) {
      navigate(agentsPath('dashboard'), { replace: true })
    }
  }, [visible, navigate])

  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      <AgentsSidebar current={current} items={items} />
      <div className="min-w-0 flex-1">
        {current === 'dashboard' ? (
          <DashboardPage />
        ) : current === 'manage' ? (
          <AgentsManagement />
        ) : current === 'tasks' ? (
          <TasksPage />
        ) : current === 'usage' ? (
          <UsagePage />
        ) : current === 'platform' ? (
          <PlatformPage />
        ) : current === 'runners' ? (
          <div className="p-8">
            <AgentRunners />
          </div>
        ) : current === 'egress' ? (
          <div className="p-8">
            <EgressDestinationManagement />
          </div>
        ) : (
          <WorkflowsManagement />
        )}
      </div>
    </div>
  )
}

function AgentsSidebar({
  current,
  items,
}: {
  current: AgentsSection
  items: AgentsNavItem[]
}) {
  const [open, setOpen] = useState(true)
  const { selectedOrganization } = useOrganization()
  const { data: agents } = useAgentList(selectedOrganization?.slug)
  const { data: waiting } = useWaitingTaskCount(selectedOrganization?.slug)
  const groups = ['Agentic platform', 'Settings'] as const

  return (
    <aside
      className={cn(
        'sticky top-16 flex h-[calc(100vh-4rem)] shrink-0 flex-col border-r border-tertiary bg-primary transition-all duration-300',
        open ? 'w-62.5' : 'w-16',
      )}
    >
      <nav
        aria-label="Agents"
        className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-3 pt-5"
      >
        {groups.map((group) => (
          <div className="flex flex-col gap-1" key={group}>
            {open && group !== 'Agentic platform' && (
              <div className="px-3 py-1 text-overline text-tertiary uppercase">
                {group}
              </div>
            )}
            {items
              .filter((item) => item.group === group)
              .map((item) => {
                const Icon = item.icon
                const active = item.id === current
                const count =
                  item.id === 'manage' && agents
                    ? String(agents.length)
                    : item.id === 'tasks' && waiting
                      ? String(waiting)
                      : ''
                return (
                  <Link
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'flex h-10 w-full items-center gap-3 rounded-md text-sm transition-colors',
                      open ? 'px-3' : 'justify-center',
                      active
                        ? 'bg-amber-bg font-medium text-amber-text'
                        : 'text-secondary hover:bg-secondary hover:text-primary',
                    )}
                    key={item.id}
                    title={
                      item.id === 'tasks' && waiting
                        ? `${waiting} waiting on you`
                        : item.label
                    }
                    to={agentsPath(item.id)}
                  >
                    <Icon className="size-4.5 shrink-0" />
                    {open && (
                      <span className="flex-1 text-left">{item.label}</span>
                    )}
                    {open && count && (
                      <span className="font-mono text-xs tabular-nums opacity-70">
                        {count}
                      </span>
                    )}
                  </Link>
                )
              })}
          </div>
        ))}
      </nav>
      <div className="shrink-0 border-t border-tertiary bg-primary px-3 py-1.5">
        <button
          aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
          className={cn(
            'flex h-10 w-full items-center gap-3 rounded-md text-sm text-secondary hover:bg-secondary hover:text-primary',
            open ? 'px-3' : 'justify-center',
          )}
          onClick={() => setOpen(!open)}
          type="button"
        >
          {open ? (
            <PanelLeftClose className="size-4.5 shrink-0" />
          ) : (
            <PanelLeftOpen className="size-4.5 shrink-0" />
          )}
          {open && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
