/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { storage } from '@/lib/storage'

type Theme = 'dark' | 'light'

const THEME_STORAGE_KEY = 'imbi-theme'

interface ThemeContextValue {
  isDarkMode: boolean
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<null | ThemeContextValue>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => readStoredTheme() ?? readSystemTheme(),
  )
  // Remembers a toggle in this session when storage is blocked.
  const explicitChoice = useRef(false)

  useLayoutEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
  }, [theme])

  // Follow OS preference when user has not explicitly chosen a theme.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (e: MediaQueryListEvent) => {
      if (!explicitChoice.current && readStoredTheme() === null) {
        setTheme(e.matches ? 'dark' : 'light')
      }
    }
    mq.addEventListener('change', handleChange)
    return () => mq.removeEventListener('change', handleChange)
  }, [])

  const value = useMemo<ThemeContextValue>(
    () => ({
      isDarkMode: theme === 'dark',
      theme,
      toggleTheme: () => {
        explicitChoice.current = true
        setTheme((prev) => {
          const next = prev === 'dark' ? 'light' : 'dark'
          storage.setItem(THEME_STORAGE_KEY, next)
          return next
        })
      },
    }),
    [theme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}

function readStoredTheme(): null | Theme {
  const stored = storage.getItem(THEME_STORAGE_KEY)
  return stored === 'dark' || stored === 'light' ? stored : null
}

function readSystemTheme(): Theme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}
