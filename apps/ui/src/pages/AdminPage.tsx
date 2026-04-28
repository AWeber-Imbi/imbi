import { Admin } from '@/components/Admin'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function AdminPage() {
  usePageTitle('Admin')
  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation currentView="admin" />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <Admin />
      </main>
      <CommandBar />
    </div>
  )
}
