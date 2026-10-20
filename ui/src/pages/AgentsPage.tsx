import { AgentsArea } from '@/components/agents/AgentsArea'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function AgentsPage() {
  usePageTitle('Agents')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="agents" />
      <main className="pt-16">
        <AgentsArea />
      </main>
    </div>
  )
}
