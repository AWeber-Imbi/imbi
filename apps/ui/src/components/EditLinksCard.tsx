import { useState, useEffect, useMemo } from 'react'
import { getIcon } from '@/lib/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import type { LinkDefinition } from '@/types'

interface EditLinksCardProps {
  linkDefs: LinkDefinition[]
  links: Record<string, string>
  isDarkMode: boolean
  isSaving: boolean
  onSave: (links: Record<string, string>) => void
}

export function EditLinksCard({
  linkDefs,
  links,
  isDarkMode,
  isSaving,
  onSave,
}: EditLinksCardProps) {
  const [urls, setUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    const initial: Record<string, string> = {}
    for (const def of linkDefs) {
      initial[def.slug] = links[def.slug] ?? ''
    }
    setUrls(initial)
  }, [linkDefs, links])

  const handleSave = () => {
    const result: Record<string, string> = {}
    for (const [slug, url] of Object.entries(urls)) {
      const trimmed = url.trim()
      if (trimmed) result[slug] = trimmed
    }
    onSave(result)
  }

  const inputClass = isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
  const headerClass = `mb-4 ${isDarkMode ? 'text-white' : 'text-slate-900'}`

  const sorted = useMemo(
    () => [...linkDefs].sort((a, b) => a.name.localeCompare(b.name)),
    [linkDefs],
  )

  return (
    <Card className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}>
      <h3 className={headerClass}>Links</h3>

      <div className="space-y-3">
        {sorted.map((def) => {
          const Icon = getIcon(def.icon)
          return (
            <div key={def.slug} className="flex items-center gap-3">
              <div
                className={`flex w-[15%] flex-shrink-0 items-center gap-2 ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}
              >
                <Icon className="h-4 w-4 flex-shrink-0" />
                <span className="truncate text-sm">{def.name}</span>
              </div>
              <Input
                value={urls[def.slug] ?? ''}
                onChange={(e) =>
                  setUrls((prev) => ({ ...prev, [def.slug]: e.target.value }))
                }
                disabled={isSaving}
                placeholder={def.url_template || 'https://...'}
                type="url"
                className={`flex-1 text-sm ${inputClass}`}
              />
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          className="border-amber-border bg-amber-bg text-amber-text hover:bg-amber-bg/80"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
