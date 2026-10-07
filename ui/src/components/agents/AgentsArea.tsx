import { useEffect, useState } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'

import { useOrganization } from '@/contexts/OrganizationContext'
import { cn } from '@/lib/utils'

import { useAgentList } from './agentQueries'
import { AgentsManagement } from './AgentsManagement'
import {
  AGENTS_NAV,
  agentsPath,
  type AgentsSection,
  isAgentsSection,
} from './agentsNav'
import { ComingSoon } from './ComingSoon'

/**
 * The Agents area: its own sidebar (Agentic platform, Settings) and the
 * page for the section in the URL.
 */
export function AgentsArea() {
  const { section } = useParams<{ section?: string }>()
  const navigate = useNavigate()
  const current: AgentsSection = isAgentsSection(section)
    ? section
    : 'dashboard'

  useEffect(() => {
    if (!isAgentsSection(section)) {
      navigate(agentsPath('dashboard'), { replace: true })
    }
  }, [section, navigate])

  return (
    <div className="flex min-h-[calc(100vh-4rem)]">
      <AgentsSidebar current={current} />
      <div className="min-w-0 flex-1">
        {current === 'manage' ? (
          <AgentsManagement />
        ) : (
          <ComingSoon section={current} />
        )}
      </div>
    </div>
  )
}

function AgentsSidebar({ current }: { current: AgentsSection }) {
  const [open, setOpen] = useState(true)
  const { selectedOrganization } = useOrganization()
  const { data: agents } = useAgentList(selectedOrganization?.slug)
  const groups = ['Agentic platform', 'Settings'] as const

  return (
    <aside
      className={cn(
        'sticky top-16 flex h-[calc(100vh-4rem)] shrink-0 flex-col border-r border-tertiary bg-primary transition-all duration-300',
        open ? 'w-62.5' : 'w-20',
      )}
    >
      <nav
        aria-label="Agents"
        className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-3 pt-5"
      >
        {groups.map((group) => (
          <div className="flex flex-col gap-1" key={group}>
            {open && group !== 'Agentic platform' && (
              <div className="text-overline text-tertiary px-3 py-1 uppercase">
                {group}
              </div>
            )}
            {AGENTS_NAV.filter((item) => item.group === group).map((item) => {
              const Icon = item.icon
              const active = item.id === current
              const count =
                item.id === 'manage' && agents ? String(agents.length) : ''
              return (
                <Link
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm transition-colors',
                    active
                      ? 'bg-amber-bg font-medium text-amber-text'
                      : 'text-secondary hover:bg-secondary hover:text-primary',
                  )}
                  key={item.id}
                  title={item.label}
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
      <div className="border-tertiary bg-primary shrink-0 border-t p-3">
        <button
          aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
          className="text-secondary hover:bg-secondary hover:text-primary flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm"
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
