import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { OperationsLog } from '@/components/OperationsLog'
import { usePageTitle } from '@/hooks/usePageTitle'

export function OperationsLogPage() {
  usePageTitle('Operations Log')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="operations" />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <OperationsLog />
      </main>
      <CommandBar />
    </div>
  )
}
