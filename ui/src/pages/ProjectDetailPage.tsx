import { useEffect } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getProject } from '@/api/endpoints'
import { Navigation } from '@/components/Navigation'
import { ProjectDetail } from '@/components/ProjectDetail'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { usePageTitle } from '@/hooks/usePageTitle'
import { parseProjectPath, projectPath } from '@/lib/project-path'

export function ProjectDetailPage() {
  const { hash, pathname, search } = useLocation()
  const navigate = useNavigate()
  const { projectId, rest, slug } = parseProjectPath(pathname)
  const [tab, subId, subAction] = rest
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

  // Legacy ID-only URLs and renamed slugs move to the canonical URL. This
  // runs as an effect so ProjectDetail stays mounted (and keeps its state)
  // when a slug edit changes the cached project.
  const canonical = project && projectPath(project, ...rest)
  const needsRedirect = !!project && slug !== project.slug
  useEffect(() => {
    if (needsRedirect && canonical) {
      navigate({ hash, pathname: canonical, search }, { replace: true })
    }
  }, [canonical, hash, navigate, needsRedirect, search])

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="projects" />
      <main className="pt-16">
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
