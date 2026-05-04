import type { ReactNode } from 'react'

import type { ProjectSchemaSectionProperty } from '@/api/endpoints'
import { pickInlineComponent } from '@/components/ui/inline-edit/field-policy'
import { InlineDate } from '@/components/ui/inline-edit/InlineDate'
import { InlineNumber } from '@/components/ui/inline-edit/InlineNumber'
import { InlineSelect } from '@/components/ui/inline-edit/InlineSelect'
import { InlineSwitch } from '@/components/ui/inline-edit/InlineSwitch'
import { InlineText } from '@/components/ui/inline-edit/InlineText'

interface InlineFieldProps {
  def: ProjectSchemaSectionProperty
  display: ReactNode
  onCommit: (value: unknown) => Promise<void>
  pending: boolean
  raw: unknown
}

export function InlineField({
  def,
  display,
  onCommit,
  pending,
  raw,
}: InlineFieldProps) {
  const kind = pickInlineComponent(def)
  switch (kind) {
    case 'date':
      return (
        <InlineDate
          mode={def.format === 'date-time' ? 'date-time' : 'date'}
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
          value={raw == null ? null : String(raw)}
        />
      )
    case 'number':
      return (
        <InlineNumber
          integer={def.type === 'integer'}
          max={def.maximum ?? undefined}
          min={def.minimum ?? undefined}
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
          value={raw == null || raw === '' ? null : Number(raw)}
        />
      )
    case 'select':
      return (
        <InlineSelect
          onCommit={onCommit}
          options={(def.enum ?? []).map((v) => ({
            label: String(v),
            value: String(v),
          }))}
          pending={pending}
          renderDisplay={display}
          value={raw == null ? null : String(raw)}
        />
      )
    case 'switch':
      return (
        <InlineSwitch
          onCommit={onCommit}
          pending={pending}
          renderDisplay={display}
          value={raw == null ? null : raw === true || raw === 'true'}
        />
      )
    default:
      return (
        <InlineText
          onCommit={onCommit}
          pending={pending}
          renderValue={display != null ? () => display : undefined}
          value={raw == null ? null : String(raw)}
        />
      )
  }
}
