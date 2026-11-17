import { Navigate, useLocation, useParams } from 'react-router-dom'

import { ticketsPath } from '@/components/agents/agentsNav'
import { TasksPage } from '@/components/agents/TasksPage'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

/** An old `/agents/tasks/...` link: go to the same ticket under `/tickets`. */
export function LegacyTasksRedirect() {
  const { action, slug, tab } = useParams()
  const { hash, search } = useLocation()
  const rest = [slug, action, tab].filter((p): p is string => !!p)
  return <Navigate replace to={`${ticketsPath(...rest)}${search}${hash}`} />
}

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
