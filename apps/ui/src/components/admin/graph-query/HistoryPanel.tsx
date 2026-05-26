import { useState } from 'react'

import { Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useGraphQuery } from '@/contexts/GraphQueryContext'

interface HistoryPanelProps {
  onLoadQuery: (query: string) => void
}

export function HistoryPanel({ onLoadQuery }: HistoryPanelProps) {
  const { clearHistory, history } = useGraphQuery()
  const [confirmOpen, setConfirmOpen] = useState(false)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="text-tertiary flex items-center justify-between px-3 pt-3 pb-2 text-[10px] tracking-wider uppercase">
        <span>History ({history.length})</span>
        <Button
          aria-label="Clear history"
          className="text-secondary hover:text-primary size-6"
          disabled={history.length === 0}
          onClick={() => setConfirmOpen(true)}
          size="icon"
          title="Clear history"
          variant="ghost"
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {history.length === 0 ? (
          <div className="text-tertiary px-2 py-4 text-xs">
            No queries run yet.
          </div>
        ) : (
          <ul className="flex flex-col gap-1">
            {history.map((entry, idx) => (
              <li key={`${entry.executedAt}-${idx}`}>
                <button
                  className="group border-tertiary hover:border-amber-border hover:bg-secondary block w-full rounded-md border px-2 py-1.5 text-left transition-colors"
                  onClick={() => onLoadQuery(entry.query)}
                  style={{ borderWidth: '0.5px' }}
                  title="Click to load into the editor"
                  type="button"
                >
                  <div className="text-primary line-clamp-2 font-mono text-[11px] break-all">
                    {entry.query}
                  </div>
                  <div className="text-tertiary mt-0.5 text-[10px]">
                    {formatTimestamp(entry.executedAt)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        confirmLabel="Clear history"
        description="This removes all queries from your local history. This cannot be undone."
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          clearHistory()
          setConfirmOpen(false)
        }}
        open={confirmOpen}
        title="Clear query history?"
      />
    </div>
  )
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  }
  return d.toLocaleDateString([], {
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
  })
}
