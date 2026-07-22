import { ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { GraphQueryInspection } from '@/types'

interface DetailDrawerProps {
  inspected: GraphQueryInspection
  onClose: () => void
}

export function DetailDrawer({ inspected, onClose }: DetailDrawerProps) {
  return (
    <aside
      className="border-tertiary flex h-full w-72 shrink-0 flex-col border-l"
      style={{ borderLeftWidth: '0.5px' }}
    >
      <div
        className="border-tertiary flex items-center gap-2 border-b px-3 py-2"
        style={{ borderBottomWidth: '0.5px' }}
      >
        <Button
          aria-label="Close details"
          className="text-secondary hover:text-primary size-6 shrink-0"
          onClick={onClose}
          size="icon"
          title="Close details"
          variant="ghost"
        >
          <ChevronRight className="size-4" />
        </Button>
        <span className="text-primary truncate font-mono text-xs">
          {inspected.heading}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {inspected.id !== undefined && <Row label="id" value={inspected.id} />}
        {inspected.entries.length === 0 ? (
          <p className="text-tertiary text-xs italic">No properties.</p>
        ) : (
          inspected.entries.map(([key, value]) => (
            <Row key={key} label={key} value={value} />
          ))
        )}
      </div>
    </aside>
  )
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div
      className="border-tertiary flex flex-col gap-0.5 border-b py-1.5 last:border-b-0"
      style={{ borderBottomWidth: '0.5px' }}
    >
      <span className="text-tertiary font-mono text-[11px] tracking-wide">
        {label}
      </span>
      <Value value={value} />
    </div>
  )
}

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-tertiary text-xs italic">null</span>
  }
  if (typeof value === 'string') {
    return <span className="text-primary text-xs wrap-break-word">{value}</span>
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return (
      <span className="text-primary font-mono text-xs">{String(value)}</span>
    )
  }
  return (
    <pre className="text-primary overflow-x-auto font-mono text-[11px] leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
