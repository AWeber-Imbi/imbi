import { useEffect, useMemo, useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { getIcon } from '@/lib/icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { SavedIndicator } from '@/components/ui/saved-indicator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSavedFlash } from '@/hooks/useSavedFlash'
import type { LinkDefinition } from '@/types'

interface EditLinksCardProps {
  linkDefs: LinkDefinition[]
  links: Record<string, string>
  onPatch: (links: Record<string, string>) => Promise<void>
}

export function EditLinksCard({
  linkDefs,
  links,
  onPatch,
}: EditLinksCardProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>(links ?? {})
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [newSlug, setNewSlug] = useState<string | null>(null)
  const [newUrl, setNewUrl] = useState('')
  const newUrlRef = useRef<HTMLInputElement>(null)
  const shouldFocusNewUrl = useRef(false)
  const { saved, flash } = useSavedFlash()

  const defBySlug = useMemo(() => {
    const m = new Map<string, LinkDefinition>()
    for (const d of linkDefs) m.set(d.slug, d)
    return m
  }, [linkDefs])

  useEffect(() => {
    setDrafts(links ?? {})
  }, [links])

  useEffect(() => {
    if (shouldFocusNewUrl.current) {
      newUrlRef.current?.focus()
      shouldFocusNewUrl.current = false
    }
  })

  const visibleSlugs = useMemo(() => {
    return Object.keys(links || {})
      .filter((slug) => defBySlug.has(slug))
      .sort((a, b) =>
        defBySlug.get(a)!.name.localeCompare(defBySlug.get(b)!.name),
      )
  }, [links, defBySlug])

  const unassignedDefs = useMemo(() => {
    const visible = new Set(visibleSlugs)
    return linkDefs
      .filter((d) => !visible.has(d.slug))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [linkDefs, visibleSlugs])

  const newSlugDef = newSlug ? defBySlug.get(newSlug) : undefined
  const NewSlugIcon = newSlugDef ? getIcon(newSlugDef.icon) : null

  const handleBlur = async (slug: string) => {
    const next = (drafts[slug] ?? '').trim()
    const current = links[slug] ?? ''
    if (next === current) return
    if (!next && current) {
      setPendingDelete(slug)
      return
    }
    const newLinks: Record<string, string> = {}
    for (const [s, v] of Object.entries({ ...links, [slug]: next })) {
      const t = (v ?? '').trim()
      if (t) newLinks[s] = t
    }
    try {
      await onPatch(newLinks)
      flash(slug)
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }

  const cancelDelete = () => {
    const slug = pendingDelete
    if (slug && links[slug]) {
      setDrafts((prev) => ({ ...prev, [slug]: links[slug] }))
    }
    setPendingDelete(null)
  }

  const requestDelete = (slug: string) => {
    if (!(links[slug] ?? '').trim()) return
    setPendingDelete(slug)
  }

  const confirmDelete = async () => {
    const slug = pendingDelete
    if (!slug) return
    const newLinks: Record<string, string> = {}
    for (const [s, v] of Object.entries(links)) {
      if (s === slug) continue
      const t = (v ?? '').trim()
      if (t) newLinks[s] = t
    }
    try {
      await onPatch(newLinks)
      setDrafts((prev) => {
        const { [slug]: _, ...rest } = prev
        return rest
      })
    } catch {
      // Parent surfaces the error.
    } finally {
      setPendingDelete(null)
    }
  }

  const handleNewSlugChange = (slug: string) => {
    if (!slug) return
    setNewSlug(slug)
    shouldFocusNewUrl.current = true
  }

  const handleNewBlur = async () => {
    const url = newUrl.trim()
    if (!newSlug || !url) return
    const newLinks: Record<string, string> = { ...links, [newSlug]: url }
    try {
      await onPatch(newLinks)
      flash(newSlug)
      setNewSlug(null)
      setNewUrl('')
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">Links</h3>

      <div className="space-y-3">
        {visibleSlugs.map((slug) => {
          const def = defBySlug.get(slug)!
          const Icon = getIcon(def.icon)
          return (
            <div key={slug} className="flex items-center gap-3">
              <div className="flex w-[15%] flex-shrink-0 items-center gap-2 text-secondary">
                <Icon className="h-4 w-4 flex-shrink-0" />
                <span className="truncate text-sm">{def.name}</span>
              </div>
              <div className="relative flex-1">
                <Input
                  value={drafts[slug] ?? ''}
                  onChange={(e) =>
                    setDrafts((prev) => ({ ...prev, [slug]: e.target.value }))
                  }
                  onBlur={() => handleBlur(slug)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      e.currentTarget.blur()
                    }
                  }}
                  placeholder={def.url_template || 'https://...'}
                  type="url"
                  className="pr-8 text-sm"
                />
                <SavedIndicator show={!!saved[slug]} />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${def.name} link`}
                className="h-8 w-8 flex-shrink-0 text-secondary hover:text-danger"
                onClick={() => requestDelete(slug)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          )
        })}

        {unassignedDefs.length > 0 && (
          <div className="flex items-center gap-3 pt-2">
            <Select value={newSlug ?? ''} onValueChange={handleNewSlugChange}>
              <SelectTrigger className="w-[15%] flex-shrink-0 text-sm">
                {newSlugDef && NewSlugIcon ? (
                  <div className="flex min-w-0 items-center gap-2 text-secondary">
                    <NewSlugIcon className="h-4 w-4 flex-shrink-0" />
                    <span className="truncate">{newSlugDef.name}</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Pick Link Type to Add" />
                )}
              </SelectTrigger>
              <SelectContent>
                {unassignedDefs.map((def) => {
                  const Icon = getIcon(def.icon)
                  return (
                    <SelectItem key={def.slug} value={def.slug}>
                      <span className="flex items-center gap-2">
                        <Icon className="h-4 w-4" />
                        {def.name}
                      </span>
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
            <Input
              ref={newUrlRef}
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              onBlur={handleNewBlur}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  e.currentTarget.blur()
                }
              }}
              placeholder={newSlugDef?.url_template || 'https://...'}
              type="url"
              disabled={!newSlug}
              className="flex-1 text-sm"
            />
            <div className="h-8 w-8 flex-shrink-0" aria-hidden />
          </div>
        )}
      </div>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={
          pendingDelete
            ? `Remove ${defBySlug.get(pendingDelete)?.name ?? 'link'}?`
            : 'Remove link?'
        }
        description="This will remove the link from the project."
        confirmLabel="Remove"
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />
    </Card>
  )
}
