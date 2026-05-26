import { useState } from 'react'

import { ChevronLeft, ChevronRight, Clock, Database, Play } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useGraphQuery } from '@/contexts/GraphQueryContext'

import { CypherEditor } from './CypherEditor'
import { HistoryPanel } from './HistoryPanel'
import { ResultCard } from './ResultCard'
import { SchemaPanel } from './SchemaPanel'

interface RailButtonProps {
  icon: React.ReactNode
  isActive: boolean
  label: string
  onClick: () => void
}

type RailItem = 'history' | 'schema'

export function GraphQueryWorkbench() {
  const { cards, editorValue, isRunning, runQuery, setEditorValue } =
    useGraphQuery()
  const [active, setActive] = useState<RailItem>('schema')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const handleRun = () => {
    if (!editorValue.trim() || isRunning) return
    void runQuery(editorValue)
  }

  const insertSnippet = (snippet: string) => {
    setEditorValue(snippet)
  }

  return (
    <div
      className="border-tertiary bg-primary flex h-[calc(100vh-12rem)] min-h-150 overflow-hidden rounded-md border"
      style={{ borderWidth: '0.5px' }}
    >
      {/* Icon rail */}
      <div
        className="border-tertiary bg-secondary flex w-12 shrink-0 flex-col items-center gap-1 border-r py-2"
        style={{ borderRightWidth: '0.5px' }}
      >
        <RailButton
          icon={<Database className="size-4" />}
          isActive={sidebarOpen && active === 'schema'}
          label="Schema"
          onClick={() => {
            if (sidebarOpen && active === 'schema') {
              setSidebarOpen(false)
            } else {
              setActive('schema')
              setSidebarOpen(true)
            }
          }}
        />
        <RailButton
          icon={<Clock className="size-4" />}
          isActive={sidebarOpen && active === 'history'}
          label="History"
          onClick={() => {
            if (sidebarOpen && active === 'history') {
              setSidebarOpen(false)
            } else {
              setActive('history')
              setSidebarOpen(true)
            }
          }}
        />
      </div>

      {/* Sidebar panel */}
      {sidebarOpen && (
        <aside
          className="border-tertiary bg-primary flex w-70 shrink-0 flex-col border-r"
          style={{ borderRightWidth: '0.5px' }}
        >
          <div
            className="border-tertiary flex items-center justify-between border-b px-3 py-2"
            style={{ borderBottomWidth: '0.5px' }}
          >
            <span className="text-secondary text-xs font-medium">
              {active === 'schema' ? 'Schema' : 'History'}
            </span>
            <Button
              aria-label="Collapse sidebar"
              className="text-secondary hover:text-primary size-6"
              onClick={() => setSidebarOpen(false)}
              size="icon"
              title="Collapse sidebar"
              variant="ghost"
            >
              <ChevronLeft className="size-4" />
            </Button>
          </div>
          <div className="flex-1 overflow-hidden">
            {active === 'schema' && (
              <SchemaPanel onInsertSnippet={insertSnippet} />
            )}
            {active === 'history' && (
              <HistoryPanel onLoadQuery={insertSnippet} />
            )}
          </div>
        </aside>
      )}

      {!sidebarOpen && (
        <div
          className="border-tertiary flex w-6 shrink-0 items-start border-r pt-2"
          style={{ borderRightWidth: '0.5px' }}
        >
          <Button
            aria-label="Expand sidebar"
            className="text-secondary hover:text-primary mx-auto size-6"
            onClick={() => setSidebarOpen(true)}
            size="icon"
            title="Expand sidebar"
            variant="ghost"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}

      {/* Workbench */}
      <div className="bg-tertiary flex min-w-0 flex-1 flex-col">
        {/* Editor card — aligned with the result cards below */}
        <div className="px-3 pt-3">
          <div
            className="border-tertiary bg-primary rounded-md border p-3"
            style={{ borderWidth: '0.5px' }}
          >
            <div className="flex items-start gap-2">
              <div className="flex-1">
                <CypherEditor
                  autoFocus
                  maxHeight="160px"
                  minHeight="32px"
                  onChange={setEditorValue}
                  onSubmit={handleRun}
                  value={editorValue}
                />
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-tertiary font-mono text-[11px]">⌘⏎</span>
                <Button
                  className="border-amber-border bg-amber-bg text-amber-text h-8 gap-1.5 border font-medium"
                  disabled={!editorValue.trim() || isRunning}
                  onClick={handleRun}
                  size="sm"
                  style={{ borderWidth: '0.5px' }}
                >
                  <Play className="size-3.5" />
                  {isRunning ? 'Running…' : 'Run'}
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Result cards */}
        <div className="flex-1 overflow-y-auto">
          {cards.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8">
              <div className="max-w-md text-center">
                <Database className="text-tertiary mx-auto mb-3 size-6" />
                <p className="text-secondary text-sm">
                  Enter a Cypher query above and press ⌘⏎ to run.
                </p>
                <p className="text-tertiary mt-1 text-xs">
                  Results will appear as cards here, newest first.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-3 p-3">
              {cards.map((card) => (
                <ResultCard card={card} key={card.id} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function RailButton({ icon, isActive, label, onClick }: RailButtonProps) {
  return (
    <button
      aria-label={label}
      className={`flex size-9 items-center justify-center rounded-md border transition-colors ${
        isActive
          ? 'border-amber-border text-amber-text bg-amber-bg'
          : 'text-secondary hover:bg-primary hover:text-primary border-transparent'
      }`}
      onClick={onClick}
      style={isActive ? { borderWidth: '0.5px' } : undefined}
      title={label}
      type="button"
    >
      {icon}
    </button>
  )
}
