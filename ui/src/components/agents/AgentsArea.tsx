import { type ReactNode, useEffect } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { AgentRunners } from '@/components/admin/AgentRunners'
import { AIModelsManagement } from '@/components/admin/AIModelsManagement'
import { EgressDestinationManagement } from '@/components/admin/EgressDestinationManagement'
import { SecretsManagement } from '@/components/admin/secrets/SecretsManagement'
import { WorkflowsManagement } from '@/components/workflows/WorkflowsManagement'

import { AgentsManagement } from './AgentsManagement'
import { agentsPath, type AgentsSection, useAgentsNav } from './agentsNav'
import { DashboardPage } from './DashboardPage'
import { PlatformPage } from './PlatformPage'

// The page of each section. The Record type makes a missing section a
// compile error.
const PAGES: Record<AgentsSection, ReactNode> = {
  'ai-models': (
    <div className="p-8">
      <AIModelsManagement />
    </div>
  ),
  dashboard: <DashboardPage />,
  egress: (
    <div className="p-8">
      <EgressDestinationManagement />
    </div>
  ),
  manage: <AgentsManagement />,
  platform: <PlatformPage />,
  runners: (
    <div className="p-8">
      <AgentRunners />
    </div>
  ),
  secrets: (
    <div className="p-8">
      <SecretsManagement />
    </div>
  ),
  workflows: <WorkflowsManagement />,
}

/**
 * The Agents area: the page for the section in the URL. The header menu
 * is the navigation between the sections.
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
    if (section === 'usage') {
      // The Usage page moved to the reports. Old links open it there.
      navigate('/reports/agent-usage', { replace: true })
    } else if (!visible) {
      navigate(agentsPath('dashboard'), { replace: true })
    }
  }, [section, visible, navigate])

  return PAGES[current]
}
