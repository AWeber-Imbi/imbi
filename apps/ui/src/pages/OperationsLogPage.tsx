import { Navigation } from '@/components/Navigation'
import { OperationsLog } from '@/components/OperationsLog'
import { CommandBar } from '@/components/CommandBar'

export function OperationsLogPage() {
  return (
    <div className="min-h-screen bg-tertiary text-primary">
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
