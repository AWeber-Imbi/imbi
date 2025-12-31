import { useState } from 'react'
import { Navigation } from '@/components/Navigation'
import { ProjectsView } from '@/components/ProjectsView'
import { Footer } from '@/components/Footer'

export function ProjectsPage() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = localStorage.getItem('imbi-theme')
    return stored === 'dark'
  })

  const handleThemeToggle = () => {
    const newValue = !isDarkMode
    setIsDarkMode(newValue)
    localStorage.setItem('imbi-theme', newValue ? 'dark' : 'light')
  }

  return (
    <div className={isDarkMode ? 'dark' : ''}>
      <div className="min-h-screen bg-background flex flex-col">
        <Navigation
          currentView="projects"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16 flex-1">
          <ProjectsView
            onProjectSelect={(projectId) => {
              console.log('Selected project:', projectId)
              // TODO: Navigate to project detail
            }}
            isDarkMode={isDarkMode}
          />
        </main>
        <Footer />
      </div>
    </div>
  )
}
