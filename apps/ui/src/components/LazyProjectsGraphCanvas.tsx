import { lazy, Suspense } from 'react'
import type { ComponentProps } from 'react'

import type { GraphProject } from '@/components/ProjectsGraphCanvas'
import { Card } from '@/components/ui/card'
import { Sk } from '@/components/ui/skeleton'

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
    <Card className="h-full p-3">
      <Sk h="100%" r={6} w="100%" />
    </Card>
  )
}
