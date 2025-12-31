import { useState, useEffect } from 'react'
import { Navigation } from '@/components/Navigation'
import { Dashboard } from '@/components/Dashboard'
import { Footer } from '@/components/Footer'

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
      <div className="min-h-screen bg-background flex flex-col">
        <Navigation
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16 flex-1">
          <Dashboard isDarkMode={isDarkMode} />
        </main>
        <Footer />
      </div>
    </div>
  )
}
