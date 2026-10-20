import { Navigation } from '@/components/Navigation'
import { ProjectsView } from '@/components/ProjectsView'
import { usePageTitle } from '@/hooks/usePageTitle'

export function ProjectsPage() {
  usePageTitle('Projects')
  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="projects" />
      <main className="pt-16">
        <ProjectsView />
      </main>
    </div>
  )
}
