import { useState } from 'react'

import { Check, Lock, Plus } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  buildRows,
  type FormatRow,
  nextRowId,
  toFormats,
} from '@/lib/versionFormats'
import type { TagFormat } from '@/types'

import { FormatEditor } from '../version-formats/FormatEditor'
import { FormatList } from '../version-formats/FormatList'

interface InheritedFormatsProps {
  inherited: TagFormat[]
}

interface OverridePanelProps {
  disabled: boolean
  onRemove: (id: string) => void
  onToggle: (id: string) => void
  onUpsert: (
    editingId: null | string,
    row: TagFormat & { example: string },
  ) => void
  ptName: string
  rows: FormatRow[]
}

interface VersionFormatsEditorProps {
  disabled?: boolean
  inherited: TagFormat[]
  onChange: (next: TagFormat[]) => void
  projectTypeName: string
  value: TagFormat[]
}

export function VersionFormatsEditor({
  disabled = false,
  inherited,
  onChange,
  projectTypeName,
  value,
}: VersionFormatsEditorProps) {
  const [override, setOverride] = useState(value.length > 0)
  const [rows, setRows] = useState<FormatRow[]>(() => buildRows(value))

  const ptName = projectTypeName.trim() || 'these'

  // The persisted output is empty when inheriting (the backend then falls back
  // to the organization defaults) and the enabled rows when overriding.
  const commit = (nextOverride: boolean, nextRows: FormatRow[]) => {
    setOverride(nextOverride)
    setRows(nextRows)
    onChange(nextOverride ? toFormats(nextRows) : [])
  }

  const handleOverrideToggle = (checked: boolean) => {
    // Seed the editable set from the inherited defaults so overriding starts
    // from the current behaviour rather than an empty (meaningless) set.
    const seeded = checked && toFormats(rows).length === 0
    commit(checked, seeded ? buildRows(inherited) : rows)
  }

  const toggleRow = (id: string) => {
    commit(
      override,
      rows.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)),
    )
  }

  const removeRow = (id: string) => {
    commit(
      override,
      rows.filter((r) => r.id !== id),
    )
  }

  const upsert = (
    editingId: null | string,
    row: TagFormat & { example: string },
  ) => {
    const next = editingId
      ? rows.map((r) => (r.id === editingId ? { ...r, ...row } : r))
      : [
          ...rows,
          {
            builtin: false,
            description: 'Custom version format.',
            enabled: true,
            id: nextRowId(),
            ...row,
          },
        ]
    commit(override, next)
  }

  const statusBadge = override ? (
    <Badge variant="warning">Overriding defaults</Badge>
  ) : (
    <Badge variant="neutral">Using defaults</Badge>
  )

  return (
    <div className="border-input border-t pt-4">
      <div className="flex items-start justify-between gap-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-foreground text-sm font-medium">
              Version formats
            </span>
            {statusBadge}
          </div>
          <p className="text-tertiary mt-1 max-w-2xl text-xs leading-relaxed">
            By default, {ptName} projects inherit the organization&apos;s
            supported version formats. Override to validate releases against a
            set specific to this project type.
          </p>
        </div>
        <Switch
          aria-label="Override organization version formats"
          checked={override}
          disabled={disabled}
          onCheckedChange={handleOverrideToggle}
        />
      </div>

      {override ? (
        <OverridePanel
          disabled={disabled}
          onRemove={removeRow}
          onToggle={toggleRow}
          onUpsert={upsert}
          ptName={ptName}
          rows={rows}
        />
      ) : (
        <InheritedFormats inherited={inherited} />
      )}
    </div>
  )
}

function InheritedFormats({ inherited }: InheritedFormatsProps) {
  return (
    <div className="border-input bg-secondary mt-4 rounded-lg border p-4">
      <div className="text-tertiary mb-3 flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
        <Lock className="size-3" />
        Inherited from organization defaults
      </div>
      {inherited.length === 0 ? (
        <p className="text-tertiary text-xs leading-relaxed">
          The organization defines no version formats, so any non-empty version
          is accepted. Set defaults in the organization&apos;s default settings,
          or override here.
        </p>
      ) : (
        <div className="space-y-2">
          {inherited.map((f) => (
            <div
              className="border-input bg-background grid grid-cols-1 items-center gap-2 rounded-lg border px-3 py-2.5 sm:grid-cols-[190px_minmax(0,1fr)]"
              key={f.pattern}
            >
              <span className="text-secondary flex items-center gap-1.5 text-sm font-medium">
                <Check className="text-success size-3.5 shrink-0" />
                {f.label}
              </span>
              <span className="text-tertiary font-mono text-xs break-all">
                {f.pattern}
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="text-tertiary mt-3 text-xs leading-relaxed">
        Managed in the organization&apos;s default settings. These apply to
        every project type that doesn&apos;t define its own.
      </p>
    </div>
  )
}

// fallow-ignore-next-line complexity
function OverridePanel({
  disabled,
  onRemove,
  onToggle,
  onUpsert,
  ptName,
  rows,
}: OverridePanelProps) {
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<FormatRow | null>(null)

  const close = () => {
    setEditing(null)
    setEditorOpen(false)
  }

  const save = (label: string, pattern: string, example: string) => {
    onUpsert(editing?.id ?? null, { example, label, pattern })
    close()
  }

  return (
    <div className="mt-4 space-y-4">
      <Alert variant="warning">
        These formats <strong>replace</strong> the organization defaults.{' '}
        {ptName} releases will be validated only against the enabled formats
        below — the inherited defaults will not apply.
      </Alert>

      <div className="flex items-center justify-between gap-3">
        <span className="text-tertiary text-xs font-semibold tracking-wide uppercase">
          Project type formats
        </span>
        <Button
          disabled={disabled}
          onClick={() => {
            setEditing(null)
            setEditorOpen(true)
          }}
          size="sm"
          variant="outline"
        >
          <Plus className="mr-1.5 size-3.5" />
          Add custom format
        </Button>
      </div>

      {editorOpen && (
        <FormatEditor
          initialExample={editing?.example}
          initialName={editing?.label}
          initialPattern={editing?.pattern}
          key={editing?.id ?? 'new'}
          onCancel={close}
          onSave={save}
          title={editing ? 'Edit custom format' : 'Add custom format'}
        />
      )}

      <FormatList
        disabled={disabled}
        onDelete={onRemove}
        onEdit={(row) => {
          setEditing(row)
          setEditorOpen(true)
        }}
        onToggle={onToggle}
        rows={rows}
      />
    </div>
  )
}
