import { useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getProject } from '@/api/endpoints'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { ProjectDetail } from '@/components/ProjectDetail'
import { Sk } from '@/components/ui/skeleton'
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
    <div className="bg-tertiary text-primary min-h-screen">
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
        {isLoading && <ProjectDetailHeaderSkeleton />}
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

const TAB_SKELETON_WIDTHS = [72, 104, 96, 88, 120, 80]

function ProjectDetailHeaderSkeleton() {
  return (
    <div className="max-w-project-detail mx-auto px-6 py-8">
      <div className="mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-3">
            <Sk h={28} r={6} w="40%" />
            <Sk h={13} w="70%" />
            <Sk h={13} w="55%" />
          </div>
          <Sk h={56} r={6} w={56} />
        </div>
      </div>
      <div className="border-tertiary mb-6 flex gap-4 border-b pb-2">
        {TAB_SKELETON_WIDTHS.map((w, i) => (
          <Sk h={15} key={i} w={w} />
        ))}
      </div>
    </div>
  )
}
