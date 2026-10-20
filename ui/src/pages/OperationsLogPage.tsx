import { useSearchParams } from 'react-router-dom'

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
      <main className="pt-16">
        <OperationsLog highlightEntryId={highlightEntryId} />
      </main>
    </div>
  )
}
