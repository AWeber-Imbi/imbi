import { Link, useParams, useSearchParams } from 'react-router-dom'

import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'

import { AgentDetail } from './AgentDetail'
import { AgentEditor } from './AgentEditor'
import { AgentList } from './AgentList'
import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'

/**
 * Settings > Agents. The URL picks the view:
 * `/agents/manage` (list), `/agents/manage/new[?from=<slug>]` (create
 * or duplicate), `/agents/manage/<slug>` (detail), and
 * `/agents/manage/<slug>/edit` (editor).
 */
export function AgentsManagement() {
  const { action, slug } = useParams<{ action?: string; slug?: string }>()
  const [searchParams] = useSearchParams()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canCreate = useHasPermission('agent:create')
  const canWrite = useHasPermission('agent:write')
  const list = useAgentList(orgSlug)
  const agents = list.data ?? []

  if (!orgSlug) {
    return (
      <div className="text-tertiary p-8 text-center">
        Select an organization to manage agents.
      </div>
    )
  }

  if (slug && list.isLoading) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <Sk h={32} r={6} w={160} />
        <Sk h={160} r={8} />
      </div>
    )
  }

  if (slug === 'new' && canCreate) {
    const from = searchParams.get('from')
    const source = from ? (agents.find((a) => a.slug === from) ?? null) : null
    return (
      <AgentEditor
        agent={null}
        key={`new:${source?.slug ?? ''}`}
        orgSlug={orgSlug}
        source={source}
      />
    )
  }

  const agent = slug ? agents.find((a) => a.slug === slug) : undefined
  if (slug && slug !== 'new' && !agent) {
    return (
      <div className="text-secondary flex flex-col items-center gap-2 p-8 text-center text-sm">
        <p>No agent with the slug “{slug}” in this organization.</p>
        <Link className="text-action" to={agentsPath('manage')}>
          Back to agents
        </Link>
      </div>
    )
  }

  if (agent && action === 'edit' && canWrite) {
    return (
      <AgentEditor
        agent={agent}
        key={agent.slug}
        orgSlug={orgSlug}
        source={null}
      />
    )
  }

  if (agent) return <AgentDetail agent={agent} />

  return (
    <div className="p-8">
      <AgentList
        agents={agents}
        error={list.error}
        loading={list.isLoading}
        orgSlug={orgSlug}
      />
    </div>
  )
}
