import { useSearchParams } from 'react-router-dom'

import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { OperationsLog } from '@/components/OperationsLog'
import { usePageTitle } from '@/hooks/usePageTitle'

export function OperationsLogPage() {
  usePageTitle('Operations Log')
  const [searchParams] = useSearchParams()
  const highlightEntryId = searchParams.get('entry') ?? undefined
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="operations" />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <OperationsLog highlightEntryId={highlightEntryId} />
      </main>
      <CommandBar />
    </div>
  )
}
