import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Navigation } from '@/components/Navigation'
import { ProjectDetail } from '@/components/ProjectDetail'
import { CommandBar } from '@/components/CommandBar'
import { useOrganization } from '@/contexts/OrganizationContext'
import { getProject } from '@/api/endpoints'

export function ProjectDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = localStorage.getItem('imbi-theme')
    return stored === 'dark'
  })

  const handleThemeToggle = () => {
    const newValue = !isDarkMode
    setIsDarkMode(newValue)
    localStorage.setItem('imbi-theme', newValue ? 'dark' : 'light')
  }

  const orgSlug = selectedOrganization?.slug || ''

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', orgSlug, slug],
    queryFn: () => getProject(orgSlug, slug!),
    enabled: !!orgSlug && !!slug,
  })

  return (
    <div className={isDarkMode ? 'dark' : ''}>
      <div className={`min-h-screen ${isDarkMode ? 'bg-gray-900 text-white' : 'bg-slate-50'}`}>
        <Navigation
          currentView="projects"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16" style={{ paddingBottom: 'var(--assistant-height, 64px)' }}>
          {isLoading && (
            <div className="max-w-7xl mx-auto px-6 py-8">
              <div className="flex items-center justify-center h-64">
                <div className="text-lg">Loading project...</div>
              </div>
            </div>
          )}
          {error && (
            <div className="max-w-7xl mx-auto px-6 py-8">
              <div className="text-center py-12 text-red-600">
                Failed to load project
              </div>
            </div>
          )}
          {project && (
            <ProjectDetail
              project={project}
              onBack={() => navigate('/projects')}
              isDarkMode={isDarkMode}
            />
          )}
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
