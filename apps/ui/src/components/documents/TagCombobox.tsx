import { useEffect, useMemo, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CornerDownLeft, Plus, Tag as TagIcon, X } from 'lucide-react'
import { toast } from 'sonner'

import { createTag, listTags } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { cn } from '@/lib/utils'
import type { Tag, TagRef } from '@/types'

import { DocumentTagChip } from './DocumentTagChip'

interface Props {
  onChange: (tags: TagRef[]) => void
  orgSlug: string
  selected: TagRef[]
  /**
   * Layout variant. `'compact'` (default) is the right-aligned inline pill
   * used in the document composer header. `'full'` stretches to fill its
   * container and uses input-sized padding/text — for use inside forms.
   */
  variant?: 'compact' | 'full'
}

/**
 * Multi-select tag combobox. Type to filter existing org tags; Enter on an
 * unmatched query creates a new tag server-side and attaches it.
 */
export function TagCombobox({
  onChange,
  orgSlug,
  selected,
  variant = 'compact',
}: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()

  const tagsKey = ['tags', orgSlug] as const
  const { data: allTags = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTags(orgSlug, signal),
    queryKey: tagsKey,
  })

  const createMutation = useMutation({
    mutationFn: (name: string) => createTag(orgSlug, { name }),
    onError: (err) => {
      toast.error(`Create tag failed: ${extractApiErrorDetail(err)}`)
    },
    onSuccess: (tag) => {
      qc.setQueryData<Tag[]>(tagsKey, (prev) => [...(prev ?? []), tag])
      onChange([...selected, { name: tag.name, slug: tag.slug }])
      setQuery('')
      setActiveIdx(0)
    },
  })

  const selectedSlugs = useMemo(
    () => new Set(selected.map((t) => t.slug)),
    [selected],
  )

  const q = query.trim().toLowerCase()
  const matches = useMemo(() => {
    return allTags.filter(
      (t) =>
        !selectedSlugs.has(t.slug) &&
        (q === '' ||
          t.name.toLowerCase().includes(q) ||
          t.slug.toLowerCase().includes(q)),
    )
  }, [allTags, selectedSlugs, q])

  const exactName = useMemo(
    () =>
      q
        ? allTags.some((t) => t.name.toLowerCase() === q) ||
          selected.some((t) => t.name.toLowerCase() === q)
        : false,
    [q, allTags, selected],
  )
  const canCreate = q.length > 0 && !exactName

  useEffect(() => {
    setActiveIdx(0)
  }, [query, open])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const addExisting = (tag: Tag | TagRef) => {
    onChange([...selected, { name: tag.name, slug: tag.slug }])
    setQuery('')
    setActiveIdx(0)
  }

  const removeTag = (slug: string) => {
    onChange(selected.filter((t) => t.slug !== slug))
  }

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, matches.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIdx < matches.length) {
        addExisting(matches[activeIdx])
      } else if (canCreate && !createMutation.isPending) {
        createMutation.mutate(query.trim())
      }
    } else if (e.key === 'Backspace' && query === '' && selected.length > 0) {
      removeTag(selected[selected.length - 1].slug)
    } else if (e.key === 'Escape') {
      setOpen(false)
      inputRef.current?.blur()
    }
  }

  const isFull = variant === 'full'

  return (
    <div
      className={cn(
        'relative flex flex-col gap-2',
        isFull ? 'w-full items-stretch' : 'items-end',
      )}
      ref={rootRef}
    >
      <div
        className={cn(
          'flex flex-wrap items-center gap-1 rounded-lg border bg-primary transition-colors',
          isFull
            ? 'w-full px-3 py-2 text-sm'
            : 'min-w-[260px] max-w-[380px] px-2 py-1 text-xs',
          open
            ? 'ring-action/20 border-action ring-2'
            : 'border-secondary hover:border-primary',
        )}
        onClick={() => {
          setOpen(true)
          inputRef.current?.focus()
        }}
      >
        <TagIcon
          className={cn(
            'flex-shrink-0 text-tertiary',
            isFull ? 'h-4 w-4' : 'h-3 w-3',
          )}
        />
        {selected.map((t) => (
          <span
            className="inline-flex items-center gap-1"
            key={t.slug}
            onClick={(e) => e.stopPropagation()}
          >
            <DocumentTagChip size="sm" tag={t} />
            <button
              aria-label={`Remove tag ${t.name}`}
              className="rounded border-0 bg-transparent p-0 text-tertiary hover:text-primary"
              onClick={() => removeTag(t.slug)}
              type="button"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        ))}
        <input
          className={cn(
            'flex-1 border-0 bg-transparent p-0 text-primary outline-none placeholder:text-tertiary',
            isFull ? 'text-sm' : 'text-xs',
          )}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKey}
          placeholder={selected.length === 0 ? 'Add tags…' : ''}
          ref={inputRef}
          style={{ minWidth: 80 }}
          value={query}
        />
      </div>

      {open && (
        <div
          className={cn(
            'absolute top-[calc(100%+6px)] z-10 max-h-80 overflow-auto rounded-lg border border-secondary bg-primary p-1 shadow-md',
            isFull ? 'left-0 w-full' : 'right-0 w-[320px]',
          )}
        >
          {matches.length > 0 && (
            <div>
              <div className="px-2 py-1 text-overline uppercase text-tertiary">
                Existing tags
              </div>
              {matches.map((t, i) => {
                const isActive = i === activeIdx
                return (
                  <button
                    className={cn(
                      'flex w-full items-center gap-2 rounded border-0 px-2 py-1.5 text-left',
                      isActive ? 'bg-secondary' : 'bg-transparent',
                    )}
                    key={t.slug}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      addExisting(t)
                    }}
                    onMouseEnter={() => setActiveIdx(i)}
                    type="button"
                  >
                    <DocumentTagChip size="sm" tag={t} />
                    <span className="ml-auto text-[11px] text-tertiary">
                      {isActive && (
                        <CornerDownLeft className="h-3 w-3 text-tertiary" />
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
          {canCreate && (
            <>
              {matches.length > 0 && <div className="my-1 h-px bg-secondary" />}
              <button
                className={cn(
                  'flex w-full items-center gap-2 rounded border-0 px-2 py-1.5 text-left text-xs text-secondary',
                  activeIdx === matches.length
                    ? 'bg-secondary'
                    : 'bg-transparent',
                )}
                disabled={createMutation.isPending}
                onMouseDown={(e) => {
                  e.preventDefault()
                  if (!createMutation.isPending)
                    createMutation.mutate(query.trim())
                }}
                onMouseEnter={() => setActiveIdx(matches.length)}
                type="button"
              >
                <Plus className="h-3 w-3 text-tertiary" />
                Create{' '}
                <span className="font-medium text-primary">“{query}”</span>
                <span className="ml-auto text-[11px] text-tertiary">Enter</span>
              </button>
            </>
          )}
          {matches.length === 0 && !canCreate && (
            <div className="px-3 py-2 text-xs text-tertiary">
              {allTags.length === 0
                ? 'No tags yet — type to create one.'
                : 'No matches.'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
