import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { Settings } from '@/components/Settings'
import { usePageTitle } from '@/hooks/usePageTitle'

export function SettingsPage() {
  usePageTitle('Settings')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
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
