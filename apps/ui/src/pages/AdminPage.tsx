import { useState } from 'react'
import { Navigation } from '@/components/Navigation'
import { CommandBar } from '@/components/CommandBar'
import { Admin } from '@/components/Admin'

const THEME_STORAGE_KEY = 'imbi-theme'

export function AdminPage() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'dark'
  })

  const handleThemeToggle = () => {
    const newValue = !isDarkMode
    setIsDarkMode(newValue)
    localStorage.setItem(THEME_STORAGE_KEY, newValue ? 'dark' : 'light')
  }

  return (
    <div className={isDarkMode ? 'dark' : ''}>
      <div className={`min-h-screen ${isDarkMode ? 'bg-gray-900 text-white' : 'bg-slate-50'}`}>
        <Navigation
          currentView="admin"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16 pb-32">
          <Admin isDarkMode={isDarkMode} />
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
