import { useState } from 'react'
import { Navigation } from '@/components/Navigation'
import { CommandBar } from '@/components/CommandBar'
import { Admin } from '@/components/Admin'
import honeycombBg from '@/assets/honeycomb_pattern_organic.png'

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
      <div className="min-h-screen bg-tertiary text-primary">
        <Navigation
          currentView="admin"
          isDarkMode={isDarkMode}
          onThemeToggle={handleThemeToggle}
        />
        <main
          className="pt-16"
          style={{
            paddingBottom: 'var(--assistant-height, 64px)',
            backgroundImage: `url(${honeycombBg})`,
            backgroundRepeat: 'repeat',
          }}
        >
          <Admin isDarkMode={isDarkMode} />
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
