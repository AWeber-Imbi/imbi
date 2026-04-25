import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Navigation } from '@/components/Navigation'
import { ProjectDetail } from '@/components/ProjectDetail'
import { CommandBar } from '@/components/CommandBar'
import { useOrganization } from '@/contexts/OrganizationContext'
import { usePageTitle } from '@/hooks/usePageTitle'
import { getProject } from '@/api/endpoints'

export function ProjectDetailPage() {
  const { projectId, tab, subId, subAction } = useParams<{
    projectId: string
    tab?: string
    subId?: string
    subAction?: string
  }>()
  const { selectedOrganization } = useOrganization()

  const orgSlug = selectedOrganization?.slug || ''

  const {
    data: project,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['project', orgSlug, projectId],
    queryFn: ({ signal }) => getProject(orgSlug, projectId!, signal),
    enabled: !!orgSlug && !!projectId,
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
            project={project}
            initialTab={tab}
            initialSubId={subId}
            initialSubAction={subAction}
          />
        )}
      </main>
      <CommandBar />
    </div>
  )
}
