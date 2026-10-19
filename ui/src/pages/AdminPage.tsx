import { Admin } from '@/components/Admin'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

export function AdminPage() {
  usePageTitle('Admin')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="admin" />
      <main className="pt-16">
        <Admin />
      </main>
    </div>
  )
}
