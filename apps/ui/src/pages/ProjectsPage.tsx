import { Navigation } from '@/components/Navigation'
import { ProjectsView } from '@/components/ProjectsView'
import { CommandBar } from '@/components/CommandBar'
import { usePageTitle } from '@/hooks/usePageTitle'

export function ProjectsPage() {
  usePageTitle('Projects')
  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation currentView="projects" />
      <main
        className="pt-16"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <ProjectsView />
      </main>
      <CommandBar />
    </div>
  )
}
