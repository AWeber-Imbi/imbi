import { useState } from 'react'
import { Navigation } from '@/components/Navigation'
import { ProjectsView } from '@/components/ProjectsView'
import { CommandBar } from '@/components/CommandBar'

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
      <div className="min-h-screen bg-tertiary text-primary">
        <Navigation
          currentView="projects"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main
          className="pt-16"
          style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
        >
          <ProjectsView isDarkMode={isDarkMode} />
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
