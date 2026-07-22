import { useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { Crosshair } from 'lucide-react'

import {
  type ConfidenceLabel,
  getConfidenceLabel,
  type SearchResult,
} from '@/api/search'
import { getResultPath } from '@/components/search/getResultPath'
import { SearchResultsSkeleton } from '@/components/search/SearchResultsSkeleton'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import {
  type EnrichedInfo,
  useSearchEnrichment,
} from '@/hooks/useSearchEnrichment'
import { deriveChipColors } from '@/lib/chip-colors'

interface SearchResultsPanelProps {
  isLoading: boolean
  limit: number
  onLimitChange: (v: number) => void
  onThresholdChange: (v: number) => void
  query: string
  results: SearchResult[]
  threshold: number
}

// ``hex`` is still the JS source of truth — it feeds ``deriveChipColors``
// for chip backgrounds, which can't read CSS variables at runtime. The
// ``dot`` / ``text`` classes reference design tokens defined in
// ``index.css`` (``--color-entity-*``) so the palette has a single owner.
const ENTITY_STYLES: Record<
  string,
  { dot: string; hex: string; label: string; round?: boolean; text: string }
> = {
  Blueprint: {
    dot: 'bg-entity-schema',
    hex: '#8C82D4',
    label: 'Blueprint',
    round: true,
    text: 'text-entity-schema',
  },
  Document: {
    dot: 'bg-entity-document',
    hex: '#D98847',
    label: 'Document',
    text: 'text-entity-document',
  },
  DocumentTemplate: {
    dot: 'bg-entity-config',
    hex: '#7A7873',
    label: 'Doc Template',
    text: 'text-entity-config',
  },
  Environment: {
    dot: 'bg-entity-config',
    hex: '#7A7873',
    label: 'Environment',
    text: 'text-entity-config',
  },
  Integration: {
    dot: 'bg-entity-config',
    hex: '#7A7873',
    label: 'Integration',
    round: true,
    text: 'text-entity-config',
  },
  LinkDefinition: {
    dot: 'bg-entity-schema',
    hex: '#8C82D4',
    label: 'Link Definition',
    round: true,
    text: 'text-entity-schema',
  },
  Organization: {
    dot: 'bg-entity-domain',
    hex: '#C86B5E',
    label: 'Organization',
    text: 'text-entity-domain',
  },
  Project: {
    dot: 'bg-entity-project',
    hex: '#5A89C9',
    label: 'Project',
    text: 'text-entity-project',
  },
  ProjectType: {
    dot: 'bg-entity-schema',
    hex: '#8C82D4',
    label: 'Project Type',
    text: 'text-entity-schema',
  },
  Release: {
    dot: 'bg-entity-domain',
    hex: '#C86B5E',
    label: 'Release',
    round: true,
    text: 'text-entity-domain',
  },
  Role: {
    dot: 'bg-entity-config',
    hex: '#7A7873',
    label: 'Role',
    round: true,
    text: 'text-entity-config',
  },
  Tag: {
    dot: 'bg-entity-domain',
    hex: '#C86B5E',
    label: 'Tag',
    round: true,
    text: 'text-entity-domain',
  },
  Team: {
    dot: 'bg-entity-config',
    hex: '#7A7873',
    label: 'Team',
    round: true,
    text: 'text-entity-config',
  },
}

const DEFAULT_ENTITY = {
  dot: 'bg-muted-foreground',
  hex: '',
  label: '',
  round: false,
  text: 'text-muted-foreground',
}

const CONFIDENCE_STYLES: Record<
  ConfidenceLabel,
  { bar: string; dot: string; text: string }
> = {
  Close: {
    bar: 'bg-blue-500',
    dot: 'bg-blue-500',
    text: 'text-blue-600 dark:text-blue-400',
  },
  Related: {
    bar: 'bg-orange-400',
    dot: 'bg-orange-400',
    text: 'text-orange-500 dark:text-orange-400',
  },
  Strong: {
    bar: 'bg-confidence-strong',
    dot: 'bg-confidence-strong',
    text: 'text-confidence-strong',
  },
}

interface ResultCardProps {
  enrichment: Map<string, EnrichedInfo>
  nameByNodeId: Map<string, string>
  onNavigate: (path: string) => void
  query: string
  result: SearchResult
}

// fallow-ignore-next-line complexity
export function SearchResultsPanel({
  isLoading,
  limit,
  onLimitChange,
  onThresholdChange,
  query,
  results,
  threshold,
}: SearchResultsPanelProps) {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const [labelFilter, setLabelFilter] = useState<null | string>('Project')
  const [refineOpen, setRefineOpen] = useState(false)
  const queryStartRef = useRef<null | number>(null)
  const [elapsedMs, setElapsedMs] = useState<null | number>(null)

  useEffect(() => {
    queryStartRef.current = Date.now()
    setElapsedMs(null)
    // Every new search starts on the Project pill, not "All".
    setLabelFilter('Project')
  }, [query])

  useEffect(() => {
    if (!isLoading && queryStartRef.current !== null && results.length > 0) {
      setElapsedMs(Date.now() - queryStartRef.current)
      queryStartRef.current = null
    }
  }, [isLoading, results])

  const enrichment = useSearchEnrichment(
    results,
    selectedOrganization?.slug ?? null,
  )

  // Build node-id → name lookup from 'name' attribute results in the same batch
  const nameByNodeId = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of results) {
      if (r.attribute === 'name') map.set(r.node_id, r.chunk_text)
    }
    return map
  }, [results])

  const visibleResults = useMemo(
    () => results.filter((r) => getConfidenceLabel(r.distance) !== null),
    [results],
  )

  const navigableResults = useMemo(
    () => visibleResults.filter((r) => getResultPath(r) !== null),
    [visibleResults],
  )

  const countsByLabel = useMemo(
    () =>
      navigableResults.reduce<Record<string, number>>((acc, r) => {
        acc[r.node_label] = (acc[r.node_label] ?? 0) + 1
        return acc
      }, {}),
    [navigableResults],
  )

  // Search defaults to the Project pill; fall back to showing all results
  // when the current query returned no rows for the selected label, so the
  // list is never empty while other results exist.
  const effectiveFilter =
    labelFilter && countsByLabel[labelFilter] ? labelFilter : null

  const filteredResults = effectiveFilter
    ? navigableResults.filter((r) => r.node_label === effectiveFilter)
    : navigableResults

  const topResult = navigableResults[0]
  const topLabel = topResult ? getConfidenceLabel(topResult.distance) : null

  if (!query.trim()) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground font-mono text-xs">
          Type to search…
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div aria-busy className="flex h-full flex-col overflow-hidden">
        <SearchResultsSkeleton />
      </div>
    )
  }

  if (!navigableResults.length) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground font-mono text-xs">
          No results found
        </p>
      </div>
    )
  }

  // fallow-ignore-next-line complexity
  const labelPills = Object.entries(countsByLabel).map(([nodeLabel, count]) => {
    const style = ENTITY_STYLES[nodeLabel] ?? DEFAULT_ENTITY
    return (
      <button
        className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs transition-colors ${
          effectiveFilter === nodeLabel
            ? 'bg-foreground text-background dark:bg-action dark:text-black'
            : 'text-muted-foreground hover:text-foreground'
        }`}
        key={nodeLabel}
        onClick={() =>
          setLabelFilter((prev) => (prev === nodeLabel ? null : nodeLabel))
        }
        type="button"
      >
        <span
          className={`size-1.5 shrink-0 ${style.round ? 'rounded-full' : 'rounded-[2px]'} ${style.dot}`}
        />
        {style.label || nodeLabel} {count}
      </button>
    )
  })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Summary header */}
      <div className="border-border text-muted-foreground flex items-center gap-2 border-b px-4 py-2 text-xs">
        <span className="font-mono">
          {navigableResults.length} results for{' '}
          <span className="text-foreground">"{query}"</span>
          {elapsedMs !== null && <> in {(elapsedMs / 1000).toFixed(3)}s</>}
          {topLabel && elapsedMs !== null && (
            <>
              {' '}
              &ndash;{' '}
              <span className={CONFIDENCE_STYLES[topLabel].text}>
                {topLabel} top match
              </span>
            </>
          )}
        </span>
        <button
          className={`border-border ml-auto flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
            refineOpen
              ? 'bg-foreground text-background'
              : 'text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => setRefineOpen((o) => !o)}
          type="button"
        >
          <Crosshair className="size-3" />
          Refine
          <span className="text-[9px]">{refineOpen ? '▲' : '▾'}</span>
        </button>
      </div>

      {/* Refine accordion */}
      <Collapsible open={refineOpen}>
        <CollapsibleContent className="border-border bg-muted/40 border-b px-4 py-3">
          <div className="mb-3 flex items-baseline gap-2">
            <span className="text-foreground text-xs font-medium">
              Refine search
            </span>
            <span className="text-muted-foreground text-xs">
              These advanced controls map to the /search API. Most users
              shouldn't need them.
            </span>
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <Label className="text-muted-foreground mb-1.5 block text-xs">
                Similarity threshold
              </Label>
              <Slider
                max={1.0}
                min={0.1}
                onValueChange={(v) => onThresholdChange(v[0])}
                step={0.05}
                value={[threshold]}
              />
              <span className="text-muted-foreground mt-1 block font-mono text-xs">
                {threshold.toFixed(2)} cosine
              </span>
            </div>
            <div>
              <Label className="text-muted-foreground mb-1.5 block text-xs">
                Max results
              </Label>
              <Slider
                max={100}
                min={5}
                onValueChange={(v) => onLimitChange(v[0])}
                step={5}
                value={[limit]}
              />
              <span className="text-muted-foreground mt-1 block font-mono text-xs">
                {limit}
              </span>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {/* Filter pills */}
      <div className="border-border flex items-center gap-1 overflow-x-auto border-b px-3 py-2">
        <button
          className={`flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${
            effectiveFilter === null
              ? 'bg-foreground text-background dark:bg-action dark:text-black'
              : 'text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => setLabelFilter(null)}
          type="button"
        >
          All {navigableResults.length}
        </button>
        {/* fallow-ignore-next-line complexity */}
        {labelPills}
      </div>

      {/* Result list */}
      <div className="flex-1 overflow-y-auto">
        {filteredResults.map((result) => (
          <ResultCard
            enrichment={enrichment}
            key={`${result.node_id}-${result.attribute}`}
            nameByNodeId={nameByNodeId}
            onNavigate={navigate}
            query={query}
            result={result}
          />
        ))}
      </div>
    </div>
  )
}

function highlightKeywords(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text
  const words = query
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 1)
  if (!words.length) return text
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = text.split(pattern)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark
            className="dark:bg-action rounded-sm bg-amber-200/80 px-0.5"
            key={i}
          >
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  )
}

// fallow-ignore-next-line complexity
function ResultCard({
  enrichment,
  nameByNodeId,
  onNavigate,
  query,
  result,
}: ResultCardProps) {
  const label = getConfidenceLabel(result.distance)!
  const entityStyle = ENTITY_STYLES[result.node_label] ?? DEFAULT_ENTITY
  const confStyle = CONFIDENCE_STYLES[label]
  const { isDarkMode } = useTheme()
  const chipColors = entityStyle.hex
    ? deriveChipColors(entityStyle.hex, isDarkMode)
    : null
  const path = getResultPath(result)
  const similarity = Math.round((1 - result.distance) * 100)

  const isNameAttr = result.attribute === 'name'
  const enriched = enrichment.get(result.node_id)
  const entityName =
    enriched?.name ?? result.name ?? nameByNodeId.get(result.node_id)
  const title =
    entityName ??
    (isNameAttr
      ? result.chunk_text
      : result.chunk_text.slice(0, 72).trimEnd() +
        (result.chunk_text.length > 72 ? '…' : ''))
  const snippet = isNameAttr || enriched?.name ? null : result.chunk_text

  const centerText = enriched?.description ?? snippet

  return (
    <button
      className={`group border-border flex w-full items-center gap-3 border-b px-4 py-2.5 text-left transition-colors ${
        path ? 'hover:bg-muted/30 cursor-pointer' : 'cursor-default'
      }`}
      onClick={() => {
        if (path) onNavigate(path)
      }}
      type="button"
    >
      {/* Badge */}
      <div
        className="shrink-0 rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap"
        style={
          chipColors
            ? {
                backgroundColor: chipColors.bg,
                border: `1px solid ${chipColors.border}`,
                color: chipColors.fg,
              }
            : undefined
        }
      >
        {entityStyle.label || result.node_label}
      </div>

      {/* Title + breadcrumb */}
      <div className="min-w-0 flex-[0_0_15%]">
        <div className="flex flex-wrap items-baseline gap-1.5">
          <span className="text-foreground text-sm leading-snug font-semibold">
            {highlightKeywords(title, query)}
          </span>
          {!isNameAttr && !enriched?.name && (
            <span className="bg-muted/60 text-muted-foreground shrink-0 rounded px-1 py-px font-mono text-xs dark:bg-white/8">
              {result.attribute}
            </span>
          )}
        </div>
        {enriched?.breadcrumb && (
          <p className="text-muted-foreground truncate text-sm">
            {enriched.breadcrumb}
          </p>
        )}
      </div>

      {/* Description / snippet — center column */}
      <div className="min-w-0 flex-1">
        {centerText && (
          <p className="text-muted-foreground truncate text-sm">
            {snippet && !enriched?.description
              ? highlightKeywords(snippet, query)
              : centerText}
          </p>
        )}
      </div>

      {/* Confidence */}
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span
          className={`flex items-center gap-1 font-mono text-xs ${confStyle.text}`}
        >
          <span className={`size-1.5 rounded-full ${confStyle.dot}`} />
          {label}
        </span>
        <div className="bg-muted h-0.5 w-14 overflow-hidden rounded-full">
          <div
            className={`h-full rounded-full transition-all ${confStyle.bar}`}
            style={{ width: `${similarity}%` }}
          />
        </div>
      </div>
    </button>
  )
}
