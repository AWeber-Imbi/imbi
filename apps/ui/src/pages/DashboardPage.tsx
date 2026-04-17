import { Navigation } from '@/components/Navigation'
import { Dashboard } from '@/components/Dashboard'
import { CommandBar } from '@/components/CommandBar'

export function DashboardPage() {
  return (
    <div className="min-h-screen bg-tertiary text-primary">
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
