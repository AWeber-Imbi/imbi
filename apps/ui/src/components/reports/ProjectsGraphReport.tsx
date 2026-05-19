import { useQuery } from '@tanstack/react-query'

import { getProjects } from '@/api/endpoints'
import { ProjectGraphView } from '@/components/ProjectGraphView'
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
      <div className="flex h-64 items-center justify-center">
        <div className="text-tertiary text-sm">Loading projects…</div>
      </div>
    )
  }

  return <ProjectGraphView projects={projects ?? []} />
}
