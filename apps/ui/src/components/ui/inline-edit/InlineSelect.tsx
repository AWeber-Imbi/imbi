import { useState } from 'react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { InlineDisplay } from './InlineDisplay'
import { toast } from 'sonner'

export interface InlineSelectOption {
  value: string
  label: string
}

export interface InlineSelectProps {
  value: string | null
  options: InlineSelectOption[]
  onCommit: (next: string) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
  placeholder?: string
  /** Override the display-mode rendering (e.g. include icon/color). */
  renderDisplay?: React.ReactNode
}

export function InlineSelect({
  value,
  options,
  onCommit,
  readOnly = false,
  pending = false,
  placeholder = 'Select…',
  renderDisplay,
}: InlineSelectProps) {
  const [editing, setEditing] = useState(false)
  const current = options.find((o) => o.value === value)

  if (!editing) {
    return (
      <InlineDisplay
        hasValue={!!current}
        readOnly={readOnly}
        pending={pending}
        onClick={() => setEditing(true)}
        placeholder={placeholder}
      >
        {renderDisplay ?? current?.label}
      </InlineDisplay>
    )
  }

  return (
    <Select
      defaultOpen
      value={value ?? undefined}
      onValueChange={async (next) => {
        setEditing(false)
        if (next === value) return
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
      onOpenChange={(open) => {
        if (!open) setEditing(false)
      }}
    >
      <SelectTrigger className="h-7 w-auto min-w-[8rem] gap-2 py-1">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
