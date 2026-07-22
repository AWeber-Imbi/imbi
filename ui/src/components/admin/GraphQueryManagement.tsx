import { GraphQueryProvider } from '@/contexts/GraphQueryContext'

import { GraphQueryWorkbench } from './graph-query/GraphQueryWorkbench'

export function GraphQueryManagement() {
  return (
    <GraphQueryProvider>
      <GraphQueryWorkbench />
    </GraphQueryProvider>
  )
}
