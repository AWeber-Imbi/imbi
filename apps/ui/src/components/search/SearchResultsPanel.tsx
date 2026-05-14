import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { Crosshair } from 'lucide-react'

import {
  type ConfidenceLabel,
  getConfidenceLabel,
  type SearchResult,
} from '@/api/search'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useSearchEnrichment } from '@/hooks/useSearchEnrichment'

interface SearchResultsPanelProps {
  isLoading: boolean
  limit: number
  onLimitChange: (v: number) => void
  onThresholdChange: (v: number) => void
  query: string
  results: SearchResult[]
  threshold: number
}

const ENTITY_STYLES: Record<
  string,
  { dot: string; label: string; round?: boolean; text: string }
> = {
  Blueprint: {
    dot: 'bg-cyan-500',
    label: 'Blueprint',
    round: true,
    text: 'text-cyan-600 dark:text-cyan-400',
  },
  Document: {
    dot: 'bg-slate-500',
    label: 'Document',
    text: 'text-slate-600 dark:text-slate-400',
  },
  DocumentTemplate: {
    dot: 'bg-slate-400',
    label: 'Doc Template',
    text: 'text-slate-500 dark:text-slate-400',
  },
  Environment: {
    dot: 'bg-indigo-500',
    label: 'Environment',
    text: 'text-indigo-600 dark:text-indigo-400',
  },
  LinkDefinition: {
    dot: 'bg-purple-500',
    label: 'Link Definition',
    round: true,
    text: 'text-purple-600 dark:text-purple-400',
  },
  Organization: {
    dot: 'bg-amber-500',
    label: 'Organization',
    text: 'text-amber-600 dark:text-amber-400',
  },
  Project: {
    dot: 'bg-blue-500',
    label: 'Project',
    text: 'text-blue-600 dark:text-blue-400',
  },
  ProjectType: {
    dot: 'bg-violet-500',
    label: 'Project Type',
    text: 'text-violet-600 dark:text-violet-400',
  },
  Release: {
    dot: 'bg-orange-500',
    label: 'Release',
    round: true,
    text: 'text-orange-600 dark:text-orange-400',
  },
  Tag: {
    dot: 'bg-green-500',
    label: 'Tag',
    round: true,
    text: 'text-green-600 dark:text-green-400',
  },
  Team: {
    dot: 'bg-teal-500',
    label: 'Team',
    round: true,
    text: 'text-teal-600 dark:text-teal-400',
  },
  ThirdPartyService: {
    dot: 'bg-emerald-500',
    label: '3rd-Party Service',
    round: true,
    text: 'text-emerald-600 dark:text-emerald-400',
  },
}

const DEFAULT_ENTITY = {
  dot: 'bg-muted-foreground',
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
    bar: 'bg-green-500',
    dot: 'bg-green-500',
    text: 'text-green-600 dark:text-green-400',
  },
}

interface ResultCardProps {
  enrichment: Map<string, { breadcrumb?: string; name?: string }>
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
  const [labelFilter, setLabelFilter] = useState<null | string>(null)
  const [refineOpen, setRefineOpen] = useState(false)
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

  const filteredResults = labelFilter
    ? navigableResults.filter((r) => r.node_label === labelFilter)
    : navigableResults

  const countsByLabel = useMemo(
    () =>
      navigableResults.reduce<Record<string, number>>((acc, r) => {
        acc[r.node_label] = (acc[r.node_label] ?? 0) + 1
        return acc
      }, {}),
    [navigableResults],
  )

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
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground animate-pulse font-mono text-xs">
          Searching…
        </p>
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
        className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] transition-colors ${
          labelFilter === nodeLabel
            ? 'border-border bg-card text-foreground'
            : 'text-muted-foreground hover:text-foreground border-transparent'
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
      <div className="border-border text-muted-foreground flex items-center gap-2 border-b px-4 py-2 text-[11px]">
        <span className="font-mono">
          {navigableResults.length} results for{' '}
          <span className="text-foreground">"{query}"</span>
        </span>
        {topLabel && (
          <>
            <span>·</span>
            <span className="flex items-center gap-1">
              <span
                className={`size-1.5 rounded-full ${CONFIDENCE_STYLES[topLabel].dot}`}
              />
              <span className={CONFIDENCE_STYLES[topLabel].text}>
                {topLabel} top match
              </span>
            </span>
          </>
        )}
        <button
          className={`border-border ml-auto flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
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
      {refineOpen && (
        <div className="border-border bg-muted/40 border-b px-4 py-3">
          <div className="mb-3 flex items-baseline gap-2">
            <span className="text-foreground text-[12px] font-medium">
              Refine search
            </span>
            <span className="text-muted-foreground text-[11px]">
              These advanced controls map to the /search API. Most users
              shouldn't need them.
            </span>
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="text-muted-foreground mb-1.5 block text-[11px]">
                Similarity threshold
              </label>
              <input
                className="w-full accent-amber-500"
                max={1.0}
                min={0.1}
                onChange={(e) => onThresholdChange(Number(e.target.value))}
                step={0.05}
                type="range"
                value={threshold}
              />
              <span className="text-muted-foreground mt-1 block font-mono text-[11px]">
                {threshold.toFixed(2)} cosine
              </span>
            </div>
            <div>
              <label className="text-muted-foreground mb-1.5 block text-[11px]">
                Max results
              </label>
              <input
                className="w-full accent-amber-500"
                max={100}
                min={5}
                onChange={(e) => onLimitChange(Number(e.target.value))}
                step={5}
                type="range"
                value={limit}
              />
              <span className="text-muted-foreground mt-1 block font-mono text-[11px]">
                {limit}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Filter pills */}
      <div className="border-border flex items-center gap-1 overflow-x-auto border-b px-3 py-2">
        <button
          className={`flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 font-mono text-[11px] font-medium transition-colors ${
            labelFilter === null
              ? 'bg-foreground text-background'
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

function getResultPath(result: SearchResult): null | string {
  if (result.node_label === 'Project') return `/projects/${result.node_id}`
  return null
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
            className="rounded-sm bg-amber-200/80 px-0.5 dark:bg-amber-800/50"
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
  const path = getResultPath(result)
  const similarity = Math.round((1 - result.distance) * 100)

  const isNameAttr = result.attribute === 'name'
  const enriched = enrichment.get(result.node_id)
  const entityName = enriched?.name ?? nameByNodeId.get(result.node_id)
  const title =
    entityName ??
    (isNameAttr
      ? result.chunk_text
      : result.chunk_text.slice(0, 72).trimEnd() +
        (result.chunk_text.length > 72 ? '…' : ''))
  const snippet = isNameAttr || enriched?.name ? null : result.chunk_text

  return (
    <button
      className={`group border-border flex w-full items-start gap-3 border-b px-4 py-3 text-left transition-colors ${
        path ? 'hover:bg-muted/30 cursor-pointer' : 'cursor-default'
      }`}
      onClick={() => {
        if (path) onNavigate(path)
      }}
      type="button"
    >
      <div
        className={`bg-muted/60 mt-0.5 flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium dark:bg-white/8 ${entityStyle.text}`}
      >
        <span
          className={`size-1.5 shrink-0 ${entityStyle.round ? 'rounded-full' : 'rounded-[2px]'} ${entityStyle.dot}`}
        />
        {entityStyle.label || result.node_label}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-1.5">
          <span className="text-foreground text-[13.5px] leading-snug font-semibold">
            {highlightKeywords(title, query)}
          </span>
          {!isNameAttr && !enriched?.name && (
            <span className="bg-muted/60 text-muted-foreground shrink-0 rounded px-1 py-px font-mono text-[10px] dark:bg-white/8">
              {result.attribute}
            </span>
          )}
        </div>
        {enriched?.breadcrumb && (
          <p className="text-muted-foreground/60 mt-0.5 font-mono text-[10px]">
            {enriched.breadcrumb}
          </p>
        )}
        {snippet && (
          <p className="text-muted-foreground mt-1 line-clamp-2 text-[12px] leading-relaxed">
            {highlightKeywords(snippet, query)}
          </p>
        )}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
        <span
          className={`flex items-center gap-1 font-mono text-[11px] ${confStyle.text}`}
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
