import { lazy, Suspense, useMemo, useState } from 'react'

import { ChevronDown, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useGraphQuery } from '@/contexts/GraphQueryContext'
import { inspectRow } from '@/lib/graphInspection'
import type {
  GraphQueryCard,
  GraphQueryCardTab,
  GraphQueryCell,
  GraphQueryCellEdge,
  GraphQueryCellNode,
  GraphQueryInspection,
} from '@/types'

import { DetailDrawer } from './DetailDrawer'

const ResultGraph = lazy(() =>
  import('./ResultGraph').then((m) => ({ default: m.ResultGraph })),
)

interface ResultCardProps {
  card: GraphQueryCard
}

const TABS: { id: GraphQueryCardTab; label: string }[] = [
  { id: 'graph', label: 'Graph' },
  { id: 'table', label: 'Table' },
  { id: 'raw', label: 'RAW' },
]

export function ResultCard({ card }: ResultCardProps) {
  const { setCardTab, toggleCardCollapsed } = useGraphQuery()
  const [inspected, setInspected] = useState<GraphQueryInspection | null>(null)

  const recordCount = card.result?.rows.length ?? 0
  const isError = card.status === 'error'

  return (
    <div
      className={`bg-primary rounded-md border ${
        isError ? 'border-destructive/40' : 'border-tertiary'
      }`}
      style={{ borderWidth: '0.5px' }}
    >
      {/* Header */}
      <div
        className="border-tertiary flex items-center gap-2 border-b px-3 py-2"
        style={{ borderBottomWidth: '0.5px' }}
      >
        <Button
          aria-label={card.collapsed ? 'Expand card' : 'Collapse card'}
          className="text-secondary hover:text-primary size-6 shrink-0"
          onClick={() => toggleCardCollapsed(card.id)}
          size="icon"
          variant="ghost"
        >
          {card.collapsed ? (
            <ChevronRight className="size-4" />
          ) : (
            <ChevronDown className="size-4" />
          )}
        </Button>
        <code
          className="text-primary flex-1 truncate font-mono text-xs"
          title={card.query}
        >
          {card.query}
        </code>
      </div>

      {!card.collapsed && (
        <>
          {/* Tabs */}
          <div
            className="border-tertiary flex items-center border-b px-3"
            style={{ borderBottomWidth: '0.5px' }}
          >
            {TABS.map((tab) => {
              const isActive = card.tab === tab.id
              return (
                <button
                  className={`-mb-px border-b px-3 py-2 text-xs transition-colors ${
                    isActive
                      ? 'border-amber-border text-amber-text font-medium'
                      : 'text-secondary hover:text-primary border-transparent'
                  }`}
                  key={tab.id}
                  onClick={() => setCardTab(card.id, tab.id)}
                  style={isActive ? { borderBottomWidth: '1.5px' } : undefined}
                  type="button"
                >
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Body */}
          <div className="flex h-120 overflow-hidden">
            <div className="min-w-0 flex-1">
              {isError ? (
                <ErrorBody card={card} />
              ) : (
                <>
                  {card.tab === 'table' && (
                    <TableTab onInspect={setInspected} result={card.result!} />
                  )}
                  {card.tab === 'graph' && (
                    <Suspense
                      fallback={
                        <div className="text-tertiary flex h-full items-center justify-center text-xs">
                          Loading graph…
                        </div>
                      }
                    >
                      <ResultGraph
                        onInspect={setInspected}
                        result={card.result!}
                      />
                    </Suspense>
                  )}
                  {card.tab === 'raw' && <RawTab result={card.result!} />}
                </>
              )}
            </div>
            {inspected && (
              <DetailDrawer
                inspected={inspected}
                onClose={() => setInspected(null)}
              />
            )}
          </div>

          {/* Footer */}
          <div
            className="border-tertiary text-tertiary flex items-center justify-between border-t px-3 py-1.5 text-[11px]"
            style={{ borderTopWidth: '0.5px' }}
          >
            {isError ? (
              <span>Failed in {card.elapsedMs ?? 0} ms</span>
            ) : (
              <span>
                Started streaming {recordCount} record
                {recordCount === 1 ? '' : 's'} in {card.elapsedMs ?? 0} ms
              </span>
            )}
            <span>{new Date(card.startedAt).toLocaleTimeString()}</span>
          </div>
        </>
      )}
    </div>
  )
}

function CellValue({ cell }: { cell: GraphQueryCell }) {
  if (cell === null || cell === undefined) {
    return <span className="text-tertiary italic">null</span>
  }
  if (isNodeCell(cell)) {
    const labels = cell.labels.length > 0 ? `:${cell.labels.join(':')}` : ''
    return (
      <span
        className="border-tertiary text-secondary inline-block max-w-full truncate rounded border bg-transparent px-1.5 py-0.5 font-mono text-[11px]"
        style={{ borderWidth: '0.5px' }}
        title={`(${labels} ${JSON.stringify(cell.properties)})`}
      >
        ({labels} {formatProps(cell.properties)})
      </span>
    )
  }
  if (isEdgeCell(cell)) {
    return (
      <span
        className="border-tertiary text-secondary inline-block max-w-full truncate rounded border bg-transparent px-1.5 py-0.5 font-mono text-[11px]"
        style={{ borderWidth: '0.5px' }}
        title={`[:${cell.type} ${JSON.stringify(cell.properties)}]`}
      >
        [:{cell.type} {formatProps(cell.properties)}]
      </span>
    )
  }
  if (typeof cell === 'string') {
    return (
      <span className="text-primary block truncate font-mono text-[11px]">
        &quot;{cell}&quot;
      </span>
    )
  }
  if (typeof cell === 'number' || typeof cell === 'boolean') {
    return (
      <span className="text-primary font-mono text-[11px]">{String(cell)}</span>
    )
  }
  return (
    <span className="text-primary block truncate font-mono text-[11px]">
      {JSON.stringify(cell)}
    </span>
  )
}

function ErrorBody({ card }: { card: GraphQueryCard }) {
  const err = card.error
  if (!err) return null
  return (
    <div className="text-primary flex h-full flex-col gap-2 overflow-y-auto p-4">
      <div className="text-destructive font-mono text-sm font-medium wrap-break-word">
        {err.message}
      </div>
      {(err.line !== undefined || err.column !== undefined) && (
        <div className="text-tertiary text-xs">
          at line {err.line ?? '?'}, column {err.column ?? '?'}
        </div>
      )}
      {err.hint && (
        <div className="text-secondary text-xs">Hint: {err.hint}</div>
      )}
      {err.code && (
        <div className="text-tertiary font-mono text-[11px]">{err.code}</div>
      )}
    </div>
  )
}

function formatProps(properties: Record<string, unknown>): string {
  const entries = Object.entries(properties).slice(0, 3)
  if (entries.length === 0) return ''
  const formatted = entries
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join(', ')
  const more = Object.keys(properties).length - entries.length
  return more > 0 ? `{${formatted}, …+${more}}` : `{${formatted}}`
}

function isEdgeCell(cell: GraphQueryCell): cell is GraphQueryCellEdge {
  return (
    typeof cell === 'object' &&
    cell !== null &&
    !Array.isArray(cell) &&
    (cell as { _kind?: string })._kind === 'edge'
  )
}

function isNodeCell(cell: GraphQueryCell): cell is GraphQueryCellNode {
  return (
    typeof cell === 'object' &&
    cell !== null &&
    !Array.isArray(cell) &&
    (cell as { _kind?: string })._kind === 'node'
  )
}

function RawTab({ result }: { result: NonNullable<GraphQueryCard['result']> }) {
  const pretty = useMemo(() => JSON.stringify(result, null, 2), [result])
  return (
    <pre className="text-primary h-full overflow-auto bg-transparent p-3 font-mono text-[11px] leading-relaxed">
      {pretty}
    </pre>
  )
}

function TableTab({
  onInspect,
  result,
}: {
  onInspect: (item: GraphQueryInspection) => void
  result: NonNullable<GraphQueryCard['result']>
}) {
  if (result.rows.length === 0) {
    return (
      <div className="text-tertiary flex h-full items-center justify-center text-xs">
        No rows returned.
      </div>
    )
  }
  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-left">
        <thead className="bg-secondary sticky top-0 z-10">
          <tr>
            {result.columns.map((col) => (
              <th
                className="border-tertiary text-secondary border-b px-2 py-1.5 text-[11px] font-medium tracking-wide"
                key={col}
                style={{ borderBottomWidth: '0.5px' }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, rowIdx) => (
            <tr
              className="border-tertiary hover:bg-secondary cursor-pointer border-b last:border-b-0"
              key={rowIdx}
              onClick={() => onInspect(inspectRow(result.columns, row))}
              style={{ borderBottomWidth: '0.5px' }}
            >
              {result.columns.map((col) => (
                <td className="max-w-[320px] px-2 py-1.5 align-top" key={col}>
                  <CellValue cell={row[col]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
