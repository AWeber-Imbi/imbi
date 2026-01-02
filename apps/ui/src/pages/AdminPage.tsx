import { useState } from 'react'
import { Navigation } from '@/components/Navigation'
import { Footer } from '@/components/Footer'
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
      <div className={`min-h-screen flex flex-col ${isDarkMode ? 'bg-gray-900 text-white' : 'bg-slate-50'}`}>
        <Navigation
          currentView="admin"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main className="pt-16 flex-1">
          <Admin isDarkMode={isDarkMode} />
        </main>
        <Footer isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
