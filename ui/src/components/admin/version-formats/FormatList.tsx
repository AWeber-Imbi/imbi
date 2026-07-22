import { Pencil, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { type FormatRow, toggleAriaLabel } from '@/lib/versionFormats'

interface FormatListProps {
  disabled?: boolean
  onDelete: (id: string) => void
  onEdit: (row: FormatRow) => void
  onToggle: (id: string) => void
  rows: FormatRow[]
}

interface FormatTableRowProps {
  disabled: boolean
  onDelete: () => void
  onEdit: () => void
  onToggle: () => void
  row: FormatRow
}

const GRID =
  'grid grid-cols-[minmax(0,1.4fr)_minmax(0,1.6fr)_auto_auto] gap-4 px-4'

export function FormatList({
  disabled = false,
  onDelete,
  onEdit,
  onToggle,
  rows,
}: FormatListProps) {
  return (
    <div className="divide-input border-input divide-y rounded-lg border">
      <div
        className={`${GRID} bg-secondary text-tertiary items-center py-2.5 text-xs font-semibold tracking-wide uppercase`}
      >
        <span>Format</span>
        <span>Pattern</span>
        <span className="text-center">On</span>
        <span className="w-14" />
      </div>
      {rows.map((row) => (
        <FormatTableRow
          disabled={disabled}
          key={row.id}
          onDelete={() => onDelete(row.id)}
          onEdit={() => onEdit(row)}
          onToggle={() => onToggle(row.id)}
          row={row}
        />
      ))}
    </div>
  )
}

function FormatTableRow({
  disabled,
  onDelete,
  onEdit,
  onToggle,
  row,
}: FormatTableRowProps) {
  return (
    <div className={`${GRID} items-start py-3.5`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-primary text-sm font-medium">{row.label}</span>
          {row.builtin ? (
            <Badge variant="neutral">Built-in</Badge>
          ) : (
            <Badge variant="accent">Custom</Badge>
          )}
        </div>
        <div className="text-tertiary mt-0.5 text-xs leading-snug">
          {row.description}
        </div>
      </div>
      <div className="min-w-0">
        <code className="bg-secondary text-secondary block rounded px-2 py-1.5 font-mono text-xs break-all">
          {row.pattern}
        </code>
        {row.example && (
          <div className="text-tertiary mt-1 text-xs">
            Matches{' '}
            <span className="text-secondary font-mono">{row.example}</span>
          </div>
        )}
      </div>
      <div className="flex justify-center pt-0.5">
        <Switch
          aria-label={toggleAriaLabel(row)}
          checked={row.enabled}
          disabled={disabled}
          onCheckedChange={onToggle}
        />
      </div>
      <div className="flex w-14 justify-end gap-0.5">
        {!row.builtin && (
          <>
            <Button
              aria-label="Edit format"
              disabled={disabled}
              onClick={onEdit}
              size="icon"
              variant="ghost"
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              aria-label="Delete format"
              disabled={disabled}
              onClick={onDelete}
              size="icon"
              variant="ghost"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
