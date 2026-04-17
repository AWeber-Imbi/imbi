import { Navigation } from '@/components/Navigation'
import { CommandBar } from '@/components/CommandBar'
import { Admin } from '@/components/Admin'

export function AdminPage() {
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
