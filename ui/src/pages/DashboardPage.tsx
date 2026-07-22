import { CommandBar } from '@/components/CommandBar'
import { Dashboard } from '@/components/Dashboard'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function DashboardPage() {
  usePageTitle('Dashboard')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <Dashboard />
      </main>
      <CommandBar />
    </div>
  )
}
