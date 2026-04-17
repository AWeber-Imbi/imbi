import { useState, useEffect, useMemo } from 'react'
import { getIcon } from '@/lib/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import type { LinkDefinition } from '@/types'

interface EditLinksCardProps {
  linkDefs: LinkDefinition[]
  links: Record<string, string>
  isSaving: boolean
  onSave: (links: Record<string, string>) => void
}

export function EditLinksCard({
  linkDefs,
  links,
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

  const sorted = useMemo(
    () => [...linkDefs].sort((a, b) => a.name.localeCompare(b.name)),
    [linkDefs],
  )

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">Links</h3>

      <div className="space-y-3">
        {sorted.map((def) => {
          const Icon = getIcon(def.icon)
          return (
            <div key={def.slug} className="flex items-center gap-3">
              <div className="flex w-[15%] flex-shrink-0 items-center gap-2 text-secondary">
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
                className="flex-1 text-sm"
              />
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
