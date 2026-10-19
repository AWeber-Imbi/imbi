import { useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  CornerDownLeft,
  FileText,
  FolderKanban,
  Search,
  Sparkles,
} from 'lucide-react'

import { getConfidenceLabel, searchOrg, type SearchResult } from '@/api/search'
import { Keystroke } from '@/components/ui/keystroke'
import { ScoreBadge } from '@/components/ui/score-badge'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  newAssistantConversation,
  useAssistantChat,
} from '@/hooks/useAssistantChat'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import {
  type EnrichedInfo,
  useSearchEnrichment,
} from '@/hooks/useSearchEnrichment'
import { cn } from '@/lib/utils'
import { useAssistantStore } from '@/stores/assistantStore'

import { getResultPath } from './getResultPath'

const PER_GROUP = 5

const GROUP_TITLES: Record<string, string> = {
  Document: 'Documents',
  DocumentTemplate: 'Document templates',
  LinkDefinition: 'Link definitions',
  Project: 'Projects',
  ProjectType: 'Project types',
}

interface Hit {
  path: string
  result: SearchResult
}

/**
 * The search box in the top bar. Cmd/Ctrl+K focuses it from anywhere;
 * results drop down grouped by type, and Tab hands the query to the
 * assistant.
 */
// fallow-ignore-next-line complexity
export function TopBarSearch() {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? null
  const { send } = useAssistantChat()
  const setPanelOpen = useAssistantStore((s) => s.setExpanded)
  const inputRef = useRef<HTMLInputElement>(null)
  const [input, setInput] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const query = useDebouncedValue(input.trim(), 200)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'k' && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  const { data: results = [], isFetching } = useQuery({
    enabled: !!query && !!orgSlug,
    queryFn: ({ signal }) =>
      searchOrg(orgSlug!, query, { limit: 20, threshold: 0.75 }, signal),
    queryKey: ['search', orgSlug, query],
    staleTime: 30_000,
  })
  const enrichment = useSearchEnrichment(results, orgSlug)
  const groups = useMemo(() => groupHits(results), [results])
  const hits = groups.flatMap(([, items]) => items)
  // The last row, after every hit, is "Ask Imbi".
  const askIndex = hits.length

  useEffect(() => setActive(0), [query])

  const close = () => {
    setOpen(false)
    inputRef.current?.blur()
  }

  const go = (hit: Hit) => {
    navigate(hit.path)
    setInput('')
    close()
  }

  const ask = () => {
    const text = input.trim()
    if (!text) return
    const top3 = results
      .filter((r) => getConfidenceLabel(r.distance) !== null)
      .slice(0, 3)
    newAssistantConversation()
    setPanelOpen(true)
    void send(buildSearchContext(text, top3), text)
    setInput('')
    close()
  }

  // fallow-ignore-next-line complexity
  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      close()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, askIndex))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Tab' && input.trim()) {
      e.preventDefault()
      ask()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (active < hits.length) go(hits[active])
      else ask()
    }
  }

  const showPanel = open && !!input.trim()
  let index = -1

  return (
    <div className="relative hidden lg:block">
      <div className="border-tertiary bg-primary focus-within:border-action flex h-9 w-72 items-center gap-2 rounded-lg border px-3 xl:w-80">
        <Search className="text-tertiary size-4 shrink-0" />
        <input
          aria-controls="top-bar-search-results"
          aria-expanded={showPanel}
          aria-label="Search Imbi"
          className="text-primary placeholder:text-tertiary min-w-0 flex-1 bg-transparent text-sm outline-none"
          onBlur={() => setOpen(false)}
          onChange={(e) => {
            setInput(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search Imbi"
          ref={inputRef}
          role="combobox"
          value={input}
        />
        <Keystroke value="Ctrl+K" />
      </div>
      {showPanel && (
        <div
          className="border-tertiary bg-primary absolute top-full right-0 z-50 mt-2 w-xl overflow-hidden rounded-xl border shadow-lg"
          id="top-bar-search-results"
          // Keep focus in the input so blur does not close the list
          // before a click lands.
          onMouseDown={(e) => e.preventDefault()}
          role="listbox"
        >
          <div className="max-h-[60vh] overflow-y-auto p-2">
            {groups.length === 0 && (
              <p className="text-tertiary px-3 py-4 text-sm">
                {isFetching || input.trim() !== query
                  ? 'Searching…'
                  : 'No results.'}
              </p>
            )}
            {groups.map(([label, items]) => (
              <div className="mb-1" key={label}>
                <div className="text-tertiary px-3 pt-2 pb-1 text-xs font-medium tracking-wide uppercase">
                  {GROUP_TITLES[label] ?? `${label}s`}
                </div>
                {items.map((hit) => {
                  index += 1
                  const i = index
                  return (
                    <HitRow
                      active={active === i}
                      enriched={enrichment.get(hit.result.node_id)}
                      hit={hit}
                      key={hit.result.node_id}
                      onHover={() => setActive(i)}
                      onSelect={() => go(hit)}
                    />
                  )
                })}
              </div>
            ))}
          </div>
          <button
            aria-selected={active === askIndex}
            className={cn(
              'flex w-full items-center gap-3 border-t border-tertiary px-5 py-3 text-left text-sm text-primary',
              active === askIndex ? 'bg-secondary' : 'bg-tertiary',
            )}
            onClick={ask}
            onMouseEnter={() => setActive(askIndex)}
            role="option"
            type="button"
          >
            <Sparkles className="text-amber-text size-4" />
            <span className="flex-1 truncate">
              Ask Imbi about “{input.trim()}”
            </span>
            <Keystroke value="Tab" />
          </button>
          <div className="border-tertiary text-tertiary flex items-center gap-4 border-t px-5 py-2 text-xs">
            <span className="flex items-center gap-1">
              <Keystroke value="ArrowUp" />
              <Keystroke value="ArrowDown" /> Navigate
            </span>
            <span className="flex items-center gap-1">
              <Keystroke value="Enter" /> Open
            </span>
            <span className="flex items-center gap-1">
              <Keystroke value="Tab" /> Ask Imbi
            </span>
            <span className="flex items-center gap-1">
              <Keystroke value="Esc" /> Close
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function buildSearchContext(query: string, results: SearchResult[]): string {
  if (results.length === 0) return query
  const lines = results.map((r, i) => {
    const label = getConfidenceLabel(r.distance) ?? 'Related'
    const snippet =
      r.chunk_text.length > 200
        ? r.chunk_text.slice(0, 200).trimEnd() + '…'
        : r.chunk_text
    return `${i + 1}. [${label}] ${r.node_label}: "${snippet}"`
  })
  return (
    `<search_context>\n` +
    `User searched for: "${query}"\n\n` +
    `Top results:\n${lines.join('\n')}\n` +
    `</search_context>\n\n` +
    query
  )
}

/**
 * One hit per node (a node matches on several attributes), only the
 * confident and navigable ones, grouped by type with projects first.
 */
function groupHits(results: SearchResult[]): [string, Hit[]][] {
  const seen = new Set<string>()
  // Projects first, then documents, then the rest as they come.
  const groups = new Map<string, Hit[]>()
  groups.set('Project', [])
  groups.set('Document', [])
  for (const result of results) {
    if (seen.has(result.node_id)) continue
    if (getConfidenceLabel(result.distance) === null) continue
    const path = getResultPath(result)
    if (!path) continue
    seen.add(result.node_id)
    const items = groups.get(result.node_label) ?? []
    if (items.length < PER_GROUP) items.push({ path, result })
    groups.set(result.node_label, items)
  }
  return [...groups.entries()].filter(([, items]) => items.length > 0)
}

function HitRow({
  active,
  enriched,
  hit,
  onHover,
  onSelect,
}: {
  active: boolean
  enriched?: EnrichedInfo
  hit: Hit
  onHover: () => void
  onSelect: () => void
}) {
  const { result } = hit
  const Icon = result.node_label === 'Document' ? FileText : FolderKanban
  const name = enriched?.name ?? result.name ?? result.chunk_text.slice(0, 72)
  const isProject = result.node_label === 'Project'
  return (
    <button
      aria-selected={active}
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left',
        active && 'bg-secondary',
      )}
      onClick={onSelect}
      onMouseEnter={onHover}
      role="option"
      type="button"
    >
      <Icon className="text-tertiary size-4 shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="text-primary block truncate text-sm font-medium">
          {name}
        </span>
        {enriched?.breadcrumb && (
          <span className="text-tertiary block truncate text-xs">
            {enriched.breadcrumb}
          </span>
        )}
      </span>
      {isProject && enriched && <ScoreBadge score={enriched.score} />}
      <CornerDownLeft
        className={cn('text-tertiary size-4', !active && 'invisible')}
      />
    </button>
  )
}
