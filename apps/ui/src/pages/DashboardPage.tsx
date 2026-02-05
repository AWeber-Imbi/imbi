import { useState, useEffect } from 'react'
import { Navigation } from '@/components/Navigation'
import { Dashboard } from '@/components/Dashboard'
import { CommandBar } from '@/components/CommandBar'

const THEME_STORAGE_KEY = 'imbi-theme'

export function DashboardPage() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    // Initialize from localStorage
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'dark'
  })

  useEffect(() => {
    // Save to localStorage whenever theme changes
    localStorage.setItem(THEME_STORAGE_KEY, isDarkMode ? 'dark' : 'light')
  }, [isDarkMode])

  const handleThemeToggle = () => {
    setIsDarkMode(!isDarkMode)
  }

  return (
    <div className={isDarkMode ? 'dark' : ''}>
      <div className={`min-h-screen ${isDarkMode ? 'bg-gray-900 text-white' : 'bg-slate-50'}`}>
        <Navigation
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16 pb-32">
          <Dashboard isDarkMode={isDarkMode} />
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
