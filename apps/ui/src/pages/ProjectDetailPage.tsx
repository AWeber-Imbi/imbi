import { useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getProject } from '@/api/endpoints'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { ProjectDetail } from '@/components/ProjectDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { usePageTitle } from '@/hooks/usePageTitle'

export function ProjectDetailPage() {
  const { projectId, subAction, subId, tab } = useParams<{
    projectId: string
    subAction?: string
    subId?: string
    tab?: string
  }>()
  const { selectedOrganization } = useOrganization()

  const orgSlug = selectedOrganization?.slug || ''

  const {
    data: project,
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) => getProject(orgSlug, projectId!, signal),
    queryKey: ['project', orgSlug, projectId],
    staleTime: 120_000,
  })

  usePageTitle(project?.name ?? 'Project')

  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation currentView="projects" />
      <main
        className="pt-16"
        style={{
          paddingBottom: 'var(--assistant-height, 64px)',
        }}
      >
        {!orgSlug && (
          <div className="mx-auto max-w-7xl px-6 py-8">
            <div className="py-12 text-center text-amber-600">
              Select an organization to view this project.
            </div>
          </div>
        )}
        {isLoading && (
          <div className="mx-auto max-w-7xl px-6 py-8">
            <div className="flex h-64 items-center justify-center">
              <div className="text-lg">Loading project...</div>
            </div>
          </div>
        )}
        {error && (
          <div className="mx-auto max-w-7xl px-6 py-8">
            <div className="py-12 text-center text-red-600">
              Failed to load project
            </div>
          </div>
        )}
        {project && (
          <ProjectDetail
            initialSubAction={subAction}
            initialSubId={subId}
            initialTab={tab}
            project={project}
          />
        )}
      </main>
      <CommandBar />
    </div>
  )
}
