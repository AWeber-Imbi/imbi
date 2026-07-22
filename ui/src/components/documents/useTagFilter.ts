import { useCallback, useMemo, useState } from 'react'

import type { Document, TagRef } from '@/types'

import { tagCounts, uniqueTagsFromDocuments } from './documentsHelpers'

/**
 * Tag-rail filter state shared by the document index views: the
 * active tag set, the rail's search text, and the documents that
 * survive both, plus the tag list/counts the rail renders.
 * `searchHaystack` controls which fields the search matches.
 */
export function useTagFilter(
  documents: Document[],
  searchHaystack: (document: Document) => string,
): {
  active: Set<string>
  clear: () => void
  counts: Record<string, number>
  filtered: Document[]
  search: string
  setSearch: (value: string) => void
  tags: TagRef[]
  toggle: (slug: string) => void
} {
  const [active, setActive] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')

  const tags = useMemo(() => uniqueTagsFromDocuments(documents), [documents])
  const counts = useMemo(() => tagCounts(documents), [documents])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return documents.filter((n) => {
      for (const slug of active) {
        if (!n.tags.some((t) => t.slug === slug)) return false
      }
      if (!q) return true
      return searchHaystack(n).toLowerCase().includes(q)
    })
  }, [documents, active, search, searchHaystack])

  const toggle = useCallback((slug: string) => {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }, [])

  const clear = useCallback(() => setActive(new Set()), [])

  return { active, clear, counts, filtered, search, setSearch, tags, toggle }
}
