import { TasksPage } from '@/components/agents/TasksPage'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function TicketsPage() {
  usePageTitle('Tickets')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="tickets" />
      <main className="pt-16">
        <TasksPage />
      </main>
    </div>
  )
}
