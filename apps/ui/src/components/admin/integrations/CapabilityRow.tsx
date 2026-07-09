import { useState } from 'react'

import {
  Box,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Copy,
  Info,
  Layers,
  Pencil,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { capabilityMeta } from '@/lib/capabilities'
import { cn } from '@/lib/utils'
import type { PluginOption } from '@/types'

import { FieldDescription } from './FieldDescription'

export interface CapabilityProjectType {
  name: string
  slug: string
}

export interface CapabilityRowProps {
  assignedTypeSlugs: string[]
  callbackUrl?: null | string
  description?: null | string
  editable?: boolean
  enabled: boolean
  kind: string
  label: string
  note?: null | string
  onAssignmentChange: (slugs: string[]) => void
  onOptionChange: (name: string, value: unknown) => void
  onToggle: (enabled: boolean) => void
  options: PluginOption[]
  optionValues: Record<string, unknown>
  projectScoped: boolean
  projectTypes: CapabilityProjectType[]
}

interface CapabilityOptionFieldProps {
  disabled: boolean
  onChange: (value: unknown) => void
  option: PluginOption
  value: unknown
}

// One capability of an integration: a toggle plus an expandable panel that
// reveals capability options, project-type assignment (zero = "all project
// types"), an optional callback URL, and an optional note.
// fallow-ignore-next-line complexity
export function CapabilityRow({
  assignedTypeSlugs,
  callbackUrl,
  description,
  editable = true,
  enabled,
  kind,
  label,
  note,
  onAssignmentChange,
  onOptionChange,
  onToggle,
  options,
  optionValues,
  projectScoped,
  projectTypes,
}: CapabilityRowProps) {
  const meta = capabilityMeta(kind)
  const Icon = meta?.icon ?? Circle
  const surfaces = meta?.surfaces ?? []

  const [expanded, setExpanded] = useState(enabled)
  const [assignMode, setAssignMode] = useState(false)
  const [copied, setCopied] = useState(false)

  const hasOptions = options.length > 0
  const hasPanel = hasOptions || projectScoped || !!note || !!callbackUrl
  const showPanel = enabled && expanded && hasPanel

  const handleToggle = (next: boolean) => {
    if (!editable) return
    onToggle(next)
    setExpanded(next)
    if (!next) setAssignMode(false)
  }

  const toggleType = (slug: string) => {
    onAssignmentChange(
      assignedTypeSlugs.includes(slug)
        ? assignedTypeSlugs.filter((s) => s !== slug)
        : [...assignedTypeSlugs, slug],
    )
  }

  const copyCallback = () => {
    if (callbackUrl && navigator.clipboard) {
      void navigator.clipboard.writeText(callbackUrl).catch(() => {})
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="border-tertiary border-b last:border-b-0">
      <div className="flex items-start gap-3.5 px-4 py-4">
        <Switch
          aria-label={`Toggle ${label}`}
          checked={enabled}
          disabled={!editable}
          onCheckedChange={handleToggle}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Icon className="text-secondary size-4 shrink-0" />
            <span className="text-primary text-sm font-semibold">{label}</span>
            <span className="flex gap-1">
              {surfaces.map((s) => (
                <span
                  className="bg-secondary text-tertiary rounded px-1.5 font-mono text-[10.5px] leading-normal"
                  key={s}
                >
                  {s}
                </span>
              ))}
            </span>
          </div>
          {description && (
            <FieldDescription
              className="text-secondary mt-1 text-[13px] leading-snug"
              text={description}
            />
          )}
        </div>
        {enabled && hasPanel && (
          <button
            className="text-tertiary hover:text-primary shrink-0 p-1"
            onClick={() => setExpanded((e) => !e)}
            type="button"
          >
            {expanded ? (
              <ChevronUp className="size-4" />
            ) : (
              <ChevronDown className="size-4" />
            )}
          </button>
        )}
      </div>

      {showPanel && (
        <div className="flex flex-col gap-4 px-4 pb-4 pl-11.5">
          {hasOptions && (
            <div className="flex flex-col gap-3">
              {options.map((opt) => (
                <CapabilityOptionField
                  disabled={!editable}
                  key={opt.name}
                  onChange={(value) => onOptionChange(opt.name, value)}
                  option={opt}
                  value={optionValues[opt.name]}
                />
              ))}
            </div>
          )}

          {projectScoped && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <div className="text-tertiary text-xs font-semibold tracking-wide uppercase">
                  Applies to
                </div>
                {editable && (
                  <Button
                    className={cn(
                      'ml-auto',
                      assignMode && 'bg-amber-bg text-amber-text',
                    )}
                    onClick={() => setAssignMode((a) => !a)}
                    size="sm"
                    variant="ghost"
                  >
                    {assignMode ? (
                      <ChevronUp className="size-3.5" />
                    ) : (
                      <Pencil className="size-3.5" />
                    )}
                    {assignMode ? 'Done' : 'Edit'}
                  </Button>
                )}
              </div>
              {assignMode ? (
                <div className="flex flex-wrap items-center gap-2">
                  {projectTypes.map((t) => {
                    const selected = assignedTypeSlugs.includes(t.slug)
                    return (
                      <button
                        className={cn(
                          'inline-flex h-7.5 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors',
                          selected
                            ? 'border-amber-border bg-amber-bg text-amber-text'
                            : 'border-secondary bg-primary text-secondary hover:bg-secondary',
                        )}
                        key={t.slug}
                        onClick={() => toggleType(t.slug)}
                        type="button"
                      >
                        <Box className="size-3.5" />
                        {t.name}
                      </button>
                    )
                  })}
                  {assignedTypeSlugs.length > 0 && (
                    <Button
                      className="text-tertiary"
                      onClick={() => onAssignmentChange([])}
                      size="sm"
                      variant="ghost"
                    >
                      <X className="size-3.5" />
                      Clear all
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2.5">
                  {assignedTypeSlugs.length === 0 ? (
                    <span className="bg-amber-bg text-amber-text inline-flex h-6.5 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium">
                      <Layers className="size-3.5" />
                      All project types
                    </span>
                  ) : (
                    projectTypes
                      .filter((t) => assignedTypeSlugs.includes(t.slug))
                      .map((t) => (
                        <span
                          className="border-secondary bg-secondary text-primary inline-flex h-6.5 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium"
                          key={t.slug}
                        >
                          <Box className="text-tertiary size-3" />
                          {t.name}
                        </span>
                      ))
                  )}
                </div>
              )}
            </div>
          )}

          {callbackUrl && (
            <div>
              <div className="text-tertiary mb-2 text-xs font-semibold tracking-wide uppercase">
                Callback URL
              </div>
              <div className="flex max-w-130 items-center gap-2">
                <code className="border-tertiary bg-secondary text-primary min-w-0 flex-1 truncate rounded-md border px-3 py-2 font-mono text-xs">
                  {callbackUrl}
                </code>
                <Button
                  className="shrink-0"
                  onClick={copyCallback}
                  size="sm"
                  variant="secondary"
                >
                  {copied ? (
                    <Check className="size-3.5" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
              <div className="text-tertiary mt-1.5 text-xs">
                Add this as an authorized redirect URL in the plugin's OAuth
                settings.
              </div>
            </div>
          )}

          {note && (
            <div className="text-secondary flex items-start gap-2 text-[13px] leading-snug">
              <Info className="text-tertiary mt-0.5 size-3.5 shrink-0" />
              <span>{note}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Render a single capability option control from its manifest declaration.
// fallow-ignore-next-line complexity
function CapabilityOptionField({
  disabled,
  onChange,
  option,
  value,
}: CapabilityOptionFieldProps) {
  const labelNode = (
    <div className="text-tertiary mb-1.5 text-xs font-semibold tracking-wide uppercase">
      {option.label}
    </div>
  )

  if (option.type === 'boolean') {
    return (
      <label className="flex items-center gap-2.5">
        <Switch
          checked={value === true}
          disabled={disabled}
          onCheckedChange={(v) => onChange(v)}
        />
        <span className="text-primary text-sm">{option.label}</span>
      </label>
    )
  }

  if (option.choices && option.choices.length > 0) {
    return (
      <div>
        {labelNode}
        <div className="max-w-90">
          <Select
            disabled={disabled}
            onValueChange={(v) => onChange(v)}
            value={typeof value === 'string' ? value : undefined}
          >
            <SelectTrigger className="h-9">
              <SelectValue placeholder="Select…" />
            </SelectTrigger>
            <SelectContent>
              {option.choices.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {choice}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {option.description && (
          <FieldDescription className="mt-1.5" text={option.description} />
        )}
      </div>
    )
  }

  return (
    <div>
      {labelNode}
      <Input
        className="max-w-90"
        disabled={disabled}
        onChange={(e) =>
          onChange(
            option.type === 'integer'
              ? e.target.value === ''
                ? null
                : Number(e.target.value)
              : e.target.value,
          )
        }
        type={
          option.type === 'integer'
            ? 'number'
            : option.type === 'secret'
              ? 'password'
              : 'text'
        }
        value={value === null || value === undefined ? '' : String(value)}
      />
      {option.description && (
        <FieldDescription className="mt-1.5" text={option.description} />
      )}
    </div>
  )
}
