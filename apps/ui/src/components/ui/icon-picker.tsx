import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Search, X } from 'lucide-react'
import * as simpleIcons from '@icons-pack/react-simple-icons'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getIcon } from '@/lib/icons'
import type { ComponentType, SVGProps } from 'react'

type IconComponent = ComponentType<
  SVGProps<SVGSVGElement> & { size?: number | string }
>

interface IconEntry {
  /** Display name, e.g. "GitHub" */
  label: string
  /** Stored value, e.g. "si-github" */
  value: string
}

// Build the index once at module level
const siLookup = simpleIcons as Record<string, unknown>
const SI_ICONS: IconEntry[] = Object.keys(siLookup)
  .filter((k) => k.startsWith('Si') && !k.endsWith('Hex') && k !== 'default')
  .map((k) => {
    // SiGithub → github, SiGoogleCloud → google-cloud
    const raw = k.slice(2)
    const kebab = raw.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
    return { label: raw, value: `si-${kebab}` }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

const MAX_RESULTS = 60

interface IconPickerProps {
  value?: string
  onChange: (value: string) => void
  isDarkMode: boolean
}

export function IconPicker({ value, onChange, isDarkMode }: IconPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    if (!query.trim()) return SI_ICONS.slice(0, MAX_RESULTS)
    const q = query.toLowerCase()
    const qNoSpace = q.replace(/\s+/g, '')
    const qHyphen = q.replace(/\s+/g, '-')
    return SI_ICONS.filter(
      (i) =>
        i.label.toLowerCase().includes(q) ||
        i.label.toLowerCase().includes(qNoSpace) ||
        i.value.includes(q) ||
        i.value.includes(qHyphen),
    ).slice(0, MAX_RESULTS)
  }, [query])

  const handleSelect = useCallback(
    (iconValue: string) => {
      onChange(iconValue)
      setOpen(false)
      setQuery('')
    },
    [onChange],
  )

  const handleClear = useCallback(() => {
    onChange('')
  }, [onChange])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const SelectedIcon: IconComponent | null = value ? getIcon(value) : null

  return (
    <div ref={containerRef} className="relative">
      {/* Current value display */}
      {value ? (
        <div
          className={`flex items-center gap-3 rounded-lg border p-2.5 ${
            isDarkMode
              ? 'border-gray-600 bg-gray-700'
              : 'border-gray-300 bg-white'
          }`}
        >
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className={`flex flex-1 items-center gap-3 text-left text-sm ${
              isDarkMode ? 'text-gray-200' : 'text-gray-900'
            }`}
          >
            {SelectedIcon && <SelectedIcon className="h-5 w-5 flex-shrink-0" />}
            <code
              className={`rounded px-1.5 py-0.5 text-xs ${
                isDarkMode ? 'bg-gray-600' : 'bg-gray-100'
              }`}
            >
              {value}
            </code>
          </button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleClear}
            aria-label="Remove icon"
            className={`h-7 w-7 p-0 ${
              isDarkMode
                ? 'text-gray-400 hover:text-red-400'
                : 'text-gray-500 hover:text-red-600'
            }`}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            isDarkMode
              ? 'border-gray-600 bg-gray-700 text-gray-400 hover:border-gray-500'
              : 'border-gray-300 bg-white text-gray-500 hover:border-gray-400'
          }`}
        >
          <Search className="h-4 w-4" />
          Pick an icon...
        </button>
      )}

      {/* Dropdown */}
      {open && (
        <div
          className={`absolute z-50 mt-1 w-full rounded-lg border shadow-lg ${
            isDarkMode
              ? 'border-gray-600 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div className="p-2">
            <div className="relative">
              <Search
                className={`absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search icons..."
                autoFocus
                className={`pl-9 ${
                  isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                }`}
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto px-2 pb-2">
            {filtered.length === 0 ? (
              <div
                className={`py-6 text-center text-sm ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`}
              >
                No icons found
              </div>
            ) : (
              <div className="grid grid-cols-6 gap-1">
                {filtered.map((icon) => {
                  const Icon = getIcon(icon.value)
                  const isSelected = value === icon.value
                  return (
                    <button
                      key={icon.value}
                      type="button"
                      title={icon.value}
                      onClick={() => handleSelect(icon.value)}
                      className={`flex h-10 w-full items-center justify-center rounded-md transition-colors ${
                        isSelected
                          ? isDarkMode
                            ? 'bg-blue-600/30 ring-1 ring-blue-500'
                            : 'bg-blue-50 ring-1 ring-blue-400'
                          : isDarkMode
                            ? 'hover:bg-gray-700'
                            : 'hover:bg-gray-100'
                      }`}
                    >
                      <Icon
                        className={`h-5 w-5 ${
                          isDarkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}
                      />
                    </button>
                  )
                })}
              </div>
            )}
            {filtered.length === MAX_RESULTS && (
              <p
                className={`mt-2 text-center text-xs ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`}
              >
                Type to narrow results
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
