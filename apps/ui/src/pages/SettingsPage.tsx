import { useState, useEffect } from 'react'
import { Navigation } from '@/components/Navigation'
import { Settings } from '@/components/Settings'
import { CommandBar } from '@/components/CommandBar'
import honeycombBg from '@/assets/honeycomb_pattern_organic.png'

const THEME_STORAGE_KEY = 'imbi-theme'

export function SettingsPage() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'dark'
  })

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, isDarkMode ? 'dark' : 'light')
  }, [isDarkMode])

  const handleThemeToggle = () => {
    setIsDarkMode(!isDarkMode)
  }

  return (
    <div className={isDarkMode ? 'dark' : ''}>
      <div className="min-h-screen bg-tertiary text-primary">
        <Navigation isDarkMode={isDarkMode} onThemeToggle={handleThemeToggle} />
        <main
          className="pt-16"
          style={{
            paddingBottom: 'var(--assistant-height, 64px)',
            backgroundImage: `url(${honeycombBg})`,
            backgroundRepeat: 'repeat',
          }}
        >
          <Settings isDarkMode={isDarkMode} />
        </main>
        <CommandBar isDarkMode={isDarkMode} />
      </div>
    </div>
  )
}
