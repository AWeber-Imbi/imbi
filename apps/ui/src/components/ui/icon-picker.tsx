import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  HoverCard,
  HoverCardTrigger,
  HoverCardContent,
} from '@/components/ui/hover-card'
import { getIcon, iconRegistry } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'

const MAX_RESULTS = 60

interface IconPickerProps {
  value?: string
  onChange: (value: string) => void
}

export function IconPicker({ value, onChange }: IconPickerProps) {
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
        <div className="flex items-center gap-3 rounded-lg border border-input bg-background p-2.5">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="flex flex-1 items-center gap-3 text-left text-sm text-primary"
          >
            {SelectedIcon && <SelectedIcon className="h-5 w-5 flex-shrink-0" />}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              {value}
            </code>
          </button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleClear}
            aria-label="Remove icon"
            className="h-7 w-7 p-0 text-tertiary hover:text-danger"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-2 rounded-lg border border-input bg-background px-3 py-2 text-sm text-tertiary hover:border-secondary"
        >
          <Search className="h-4 w-4" />
          Pick an icon...
        </button>
      )}

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-card shadow-lg">
          <div className="p-2">
            <div className="mb-2 flex flex-wrap gap-1">
              {sets.map((set) => (
                <button
                  key={set.id}
                  type="button"
                  onClick={() => {
                    setIconSet(set.id)
                  }}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    iconSet === set.id
                      ? 'bg-info text-info'
                      : 'text-tertiary hover:text-secondary'
                  }`}
                >
                  {set.label}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search icons..."
                autoFocus
                className={`pl-9 ${''}`}
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto px-2 pb-2">
            {filtered.length === 0 ? (
              <div className="py-6 text-center text-sm text-tertiary">
                No icons found
              </div>
            ) : (
              <div className="grid grid-cols-6 gap-1">
                {filtered.map((icon) => {
                  const Icon = getIcon(icon.value, null)
                  if (!Icon) return null
                  const isSelected = value === icon.value
                  return (
                    <HoverCard
                      key={icon.value}
                      openDelay={300}
                      closeDelay={100}
                    >
                      <HoverCardTrigger asChild>
                        <button
                          type="button"
                          onClick={() => handleSelect(icon.value)}
                          className={`flex h-10 w-full items-center justify-center rounded-md transition-colors ${
                            isSelected
                              ? 'bg-info ring-1 ring-info'
                              : 'hover:bg-secondary'
                          }`}
                        >
                          <Icon className="h-5 w-5 text-secondary" />
                        </button>
                      </HoverCardTrigger>
                      <HoverCardContent className="w-auto p-4" side="top">
                        <div className="flex flex-col items-center gap-3">
                          <Icon className="h-20 w-20 text-primary" />
                          <span className="max-w-[180px] break-all text-center text-sm text-muted-foreground">
                            {icon.label}
                          </span>
                        </div>
                      </HoverCardContent>
                    </HoverCard>
                  )
                })}
              </div>
            )}
            {filtered.length === MAX_RESULTS && (
              <p className="mt-2 text-center text-xs text-tertiary">
                Type to narrow results
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
