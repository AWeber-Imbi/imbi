import type { ReactNode } from 'react'
import type { ProjectSchemaSectionProperty } from '@/api/endpoints'
import { pickInlineComponent } from '@/components/ui/inline-edit/field-policy'
import { InlineText } from '@/components/ui/inline-edit/InlineText'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineSwitch } from '@/components/ui/inline-edit/InlineSwitch'
import { InlineNumber } from '@/components/ui/inline-edit/InlineNumber'
import { InlineDate } from '@/components/ui/inline-edit/InlineDate'

interface InlineFieldProps {
  def: ProjectSchemaSectionProperty
  raw: unknown
  onCommit: (value: unknown) => Promise<void>
  pending: boolean
  display: ReactNode
}

export function InlineField({
  def,
  raw,
  onCommit,
  pending,
  display,
}: InlineFieldProps) {
  const kind = pickInlineComponent(def)
  switch (kind) {
    case 'select':
      return (
        <InlineSelect
          value={raw == null ? null : String(raw)}
          options={(def.enum ?? []).map((v) => ({
            value: String(v),
            label: String(v),
          }))}
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
        />
      )
    case 'switch':
      return (
        <InlineSwitch
          value={raw === true || raw === 'true'}
          onCommit={onCommit}
          pending={pending}
        />
      )
    case 'number':
      return (
        <InlineNumber
          value={raw == null || raw === '' ? null : Number(raw)}
          integer={def.type === 'integer'}
          min={def.minimum ?? undefined}
          max={def.maximum ?? undefined}
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
        />
      )
    case 'date':
      return (
        <InlineDate
          value={raw == null ? null : String(raw)}
          mode={def.format === 'date-time' ? 'date-time' : 'date'}
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
        />
      )
    default:
      return (
        <InlineText
          value={raw == null ? null : String(raw)}
          onCommit={onCommit}
          pending={pending}
          renderValue={display != null ? () => display : undefined}
        />
      )
  }
}
