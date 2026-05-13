import { useState } from 'react'

import { toast } from 'sonner'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { InlineDisplay } from './InlineDisplay'

export interface InlineSelectOption {
  label: string
  value: string
}

export interface InlineSelectProps {
  onCommit: (next: string) => Promise<void> | void
  options: InlineSelectOption[]
  pending?: boolean
  placeholder?: string
  readOnly?: boolean
  /** Override the display-mode rendering (e.g. include icon/color). */
  renderDisplay?: React.ReactNode
  value: null | string
}

export function InlineSelect({
  onCommit,
  options,
  pending = false,
  placeholder = 'Select…',
  readOnly = false,
  renderDisplay,
  value,
}: InlineSelectProps) {
  const [editing, setEditing] = useState(false)
  const current = options.find((o) => o.value === value)

  if (!editing) {
    return (
      <InlineDisplay
        hasValue={!!current}
        onClick={() => setEditing(true)}
        pending={pending}
        placeholder={placeholder}
        readOnly={readOnly}
      >
        {renderDisplay ?? current?.label}
      </InlineDisplay>
    )
  }

  return (
    <Select
      defaultOpen
      onOpenChange={(open) => {
        if (!open) setEditing(false)
      }}
      onValueChange={async (next) => {
        setEditing(false)
        if (next === value) return
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
      value={value ?? undefined}
    >
      <SelectTrigger className="h-7 w-auto min-w-32 gap-2 py-1">
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
