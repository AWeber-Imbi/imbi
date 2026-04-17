import { Navigation } from '@/components/Navigation'
import { Settings } from '@/components/Settings'
import { CommandBar } from '@/components/CommandBar'

export function SettingsPage() {
  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <Settings />
      </main>
      <CommandBar />
    </div>
  )
}
