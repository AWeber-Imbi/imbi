import { useSearchParams } from 'react-router-dom'

import { OperationsLog } from '@/components/OperationsLog'

export function OperationsLogReport() {
  const [searchParams] = useSearchParams()
  return (
    <OperationsLog
      embedded
      highlightEntryId={searchParams.get('entry') ?? undefined}
      showHeader={false}
    />
  )
}
