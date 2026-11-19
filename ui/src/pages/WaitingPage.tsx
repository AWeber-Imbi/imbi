import { WaitingOnMe } from '@/components/agents/WaitingOnMe'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function WaitingPage() {
  usePageTitle('Waiting on me')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="tickets" />
      <main className="pt-16">
        <WaitingOnMe />
      </main>
    </div>
  )
}
