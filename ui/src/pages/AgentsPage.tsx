import { AgentsArea } from '@/components/agents/AgentsArea'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function AgentsPage() {
  usePageTitle('Agents')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="agents" />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <AgentsArea />
      </main>
      <CommandBar />
    </div>
  )
}
