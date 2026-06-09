import * as React from 'react'

import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { KeyValueEditor } from '@/components/ui/key-value-editor'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { PluginOptionDef } from '@/types'

export interface OptionRowProps {
  description: null | string
  label: string
  name: string
  onChange: (next: unknown) => void
  opt: PluginOptionDef
  placeholder?: string
  value: unknown
}

interface ControlProps {
  id: string
  onChange: (next: unknown) => void
  opt: PluginOptionDef
  placeholder?: string
  value: unknown
}

export function OptionRow({
  description,
  label,
  name,
  onChange,
  opt,
  placeholder,
  value,
}: OptionRowProps) {
  const id = `option-${name}`
  return (
    <div className="grid grid-cols-[160px_1fr] items-center gap-3">
      <Label className="truncate text-xs" htmlFor={id} title={label}>
        {label}
        {opt.required && <span className="text-destructive ml-1">*</span>}
      </Label>
      <div className="space-y-1">
        {renderControl({ id, onChange, opt, placeholder, value })}
        {description && <p className="text-secondary text-xs">{description}</p>}
      </div>
    </div>
  )
}

function BooleanControl({ id, onChange, value }: ControlProps) {
  return (
    <Checkbox
      checked={Boolean(value)}
      id={id}
      onCheckedChange={(checked) => onChange(checked === true)}
    />
  )
}

function ChoiceControl({
  id,
  onChange,
  opt,
  placeholder,
  value,
}: ControlProps) {
  return (
    <Select
      onValueChange={(v) => onChange(v)}
      value={typeof value === 'string' ? value : ''}
    >
      <SelectTrigger id={id}>
        <SelectValue placeholder={placeholder ?? 'Select…'} />
      </SelectTrigger>
      <SelectContent>
        {(opt.choices ?? []).map((c) => (
          <SelectItem key={c} value={c}>
            {c}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function IntegerControl({ id, onChange, placeholder, value }: ControlProps) {
  return (
    <Input
      id={id}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '') {
          onChange(null)
          return
        }
        const n = Number.parseInt(raw, 10)
        if (!Number.isNaN(n)) onChange(n)
      }}
      placeholder={placeholder}
      type="number"
      value={
        typeof value === 'number' ? String(value) : (value as string) || ''
      }
    />
  )
}

function MappingControl({ onChange, value }: ControlProps) {
  const record =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, number | string>)
      : {}
  return <KeyValueEditor onChange={(next) => onChange(next)} value={record} />
}

const CONTROLS_BY_TYPE: Record<
  PluginOptionDef['type'],
  (p: ControlProps) => React.ReactNode
> = {
  boolean: (p) => <BooleanControl {...p} />,
  integer: (p) => <IntegerControl {...p} />,
  mapping: (p) => <MappingControl {...p} />,
  secret: (p) => <TextControl {...p} />,
  string: (p) => <TextControl {...p} />,
}

function renderControl(props: ControlProps): React.ReactNode {
  if (props.opt.choices && props.opt.choices.length > 0) {
    return <ChoiceControl {...props} />
  }
  return CONTROLS_BY_TYPE[props.opt.type](props)
}

function TextControl({ id, onChange, opt, placeholder, value }: ControlProps) {
  return (
    <Input
      id={id}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      type={opt.type === 'secret' ? 'password' : 'text'}
      value={(value as string) ?? ''}
    />
  )
}
