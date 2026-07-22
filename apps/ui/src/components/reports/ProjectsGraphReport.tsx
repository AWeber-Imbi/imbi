import { useQuery } from '@tanstack/react-query'

import { getProjects } from '@/api/endpoints'
import { ProjectGraphView } from '@/components/ProjectGraphView'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'

// fallow-ignore-next-line complexity
export function ProjectsGraphReport() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const {
    data: projects,
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  if (error) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-danger text-sm">
          Failed to load projects:{' '}
          {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div
        style={{
          height: 'calc(100vh - 280px - var(--assistant-height, 64px))',
        }}
      >
        <Sk h="100%" r={8} w="100%" />
      </div>
    )
  }

  return <ProjectGraphView projects={projects ?? []} />
}
