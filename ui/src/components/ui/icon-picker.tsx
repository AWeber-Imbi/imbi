import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Search, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card'
import { Input } from '@/components/ui/input'
import { getIcon, iconRegistry, useIconRegistryVersion } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'

const MAX_RESULTS = 60

interface IconPickerProps {
  onChange: (value: string) => void
  value?: string
}

export function IconPicker({ onChange, value }: IconPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [iconSet, setIconSet] = useState('lucide')
  const containerRef = useRef<HTMLDivElement>(null)

  const version = useIconRegistryVersion()
  // Metas are known up-front from loader registration; the set's actual
  // icons arrive async once the chunk for `iconSet` has loaded.
  const setMetas = useMemo(
    () => iconRegistry.getSetMetas(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [version],
  )
  const currentSet = iconRegistry.getLoadedSet(iconSet)
  const icons = useMemo(
    () => currentSet?.icons ?? [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentSet, version],
  )

  useEffect(() => {
    if (open && !iconRegistry.isLoaded(iconSet)) {
      void iconRegistry.loadSet(iconSet)
    }
  }, [open, iconSet])

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
    <div className="relative" ref={containerRef}>
      {/* Current value display */}
      {value ? (
        <div className="border-input bg-background flex items-center gap-3 rounded-lg border p-2.5">
          <button
            className="text-primary flex flex-1 items-center gap-3 text-left text-sm"
            onClick={() => setOpen(!open)}
            type="button"
          >
            {SelectedIcon && <SelectedIcon className="size-5 shrink-0" />}
            <code className="bg-secondary rounded px-1.5 py-0.5 text-xs">
              {value}
            </code>
          </button>
          <Button
            aria-label="Remove icon"
            className="text-tertiary hover:text-danger size-7 p-0"
            onClick={handleClear}
            size="sm"
            type="button"
            variant="ghost"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      ) : (
        <button
          className="border-input bg-background text-tertiary hover:border-secondary flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm"
          onClick={() => setOpen(!open)}
          type="button"
        >
          <Search className="size-4" />
          Pick an icon...
        </button>
      )}

      {/* Dropdown */}
      {open && (
        <div className="border-border bg-card absolute z-50 mt-1 w-full rounded-lg border shadow-lg">
          <div className="p-2">
            <div className="mb-2 flex flex-wrap gap-1">
              {setMetas.map((set) => (
                <button
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    iconSet === set.id
                      ? 'bg-info text-info'
                      : 'text-tertiary hover:text-secondary'
                  }`}
                  key={set.id}
                  onClick={() => {
                    setIconSet(set.id)
                  }}
                  type="button"
                >
                  {set.label}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search className="text-tertiary absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
              <Input
                autoFocus
                className={`pl-9 ${''}`}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search icons..."
                value={query}
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto px-2 pb-2">
            {!currentSet ? (
              <div className="text-tertiary py-6 text-center text-sm">
                Loading icons…
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-tertiary py-6 text-center text-sm">
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
                      closeDelay={100}
                      key={icon.value}
                      openDelay={300}
                    >
                      <HoverCardTrigger asChild>
                        <button
                          className={`flex h-10 w-full items-center justify-center rounded-md transition-colors ${
                            isSelected
                              ? 'bg-info ring-info ring-1'
                              : 'hover:bg-secondary'
                          }`}
                          onClick={() => handleSelect(icon.value)}
                          type="button"
                        >
                          <Icon className="text-secondary size-5" />
                        </button>
                      </HoverCardTrigger>
                      <HoverCardContent className="w-auto p-4" side="top">
                        <div className="flex flex-col items-center gap-3">
                          <Icon className="text-primary size-20" />
                          <span className="text-muted-foreground max-w-45 text-center text-sm break-all">
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
              <p className="text-tertiary mt-2 text-center text-xs">
                Type to narrow results
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
