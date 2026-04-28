import { lazy, Suspense } from 'react'
import type { ComponentProps } from 'react'

import type { GraphProject } from '@/components/ProjectsGraphCanvas'
import { Card } from '@/components/ui/card'

export type { GraphProject }

const ProjectsGraphCanvas = lazy(() =>
  import('@/components/ProjectsGraphCanvas').then((m) => ({
    default: m.ProjectsGraphCanvas,
  })),
)

type ProjectsGraphCanvasProps = ComponentProps<typeof ProjectsGraphCanvas>

export function LazyProjectsGraphCanvas(props: ProjectsGraphCanvasProps) {
  return (
    <Suspense fallback={<GraphFallback />}>
      <ProjectsGraphCanvas {...props} />
    </Suspense>
  )
}

function GraphFallback() {
  return (
    <Card className="flex items-center justify-center p-12">
      <div className="flex flex-col items-center gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent opacity-50" />
        <p className="text-sm text-tertiary">Loading graph…</p>
      </div>
    </Card>
  )
}
