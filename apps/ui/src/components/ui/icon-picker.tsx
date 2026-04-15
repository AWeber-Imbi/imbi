import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getIcon, iconRegistry } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'

const MAX_RESULTS = 60

interface IconPickerProps {
  value?: string
  onChange: (value: string) => void
  isDarkMode: boolean
}

export function IconPicker({ value, onChange, isDarkMode }: IconPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [iconSet, setIconSet] = useState('lucide')
  const containerRef = useRef<HTMLDivElement>(null)

  const sets = iconRegistry.getSets()
  const currentSet = sets.find((s) => s.id === iconSet)
  const icons = useMemo(() => currentSet?.icons ?? [], [currentSet])

  const filtered = useMemo(() => {
    if (!query.trim()) return icons.slice(0, MAX_RESULTS)
    const q = query.toLowerCase()
    const qNoSpace = q.replace(/\s+/g, '')
    const qHyphen = q.replace(/\s+/g, '-')
    return icons
      .filter(
        (i) =>
          i.label.toLowerCase().includes(q) ||
          i.label.toLowerCase().includes(qNoSpace) ||
          i.value.includes(q) ||
          i.value.includes(qHyphen),
      )
      .slice(0, MAX_RESULTS)
  }, [query, icons])

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
            <div className="mb-2 flex flex-wrap gap-1">
              {sets.map((set) => (
                <button
                  key={set.id}
                  type="button"
                  onClick={() => {
                    setIconSet(set.id)
                    setQuery('')
                  }}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    iconSet === set.id
                      ? isDarkMode
                        ? 'bg-blue-600/30 text-blue-300'
                        : 'bg-blue-50 text-blue-700'
                      : isDarkMode
                        ? 'text-gray-400 hover:text-gray-200'
                        : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {set.label}
                </button>
              ))}
            </div>
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
                  const Icon = getIcon(icon.value, null)
                  if (!Icon) return null
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
