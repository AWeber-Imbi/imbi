import { useRef, useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Save } from 'lucide-react'

import { updateOrganization } from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'
import { buildDiffPatch } from '@/lib/json-patch'
import {
  buildRows,
  type FormatRow,
  nextRowId,
  toFormats,
} from '@/lib/versionFormats'
import type { PatchOperation, TagFormat } from '@/types'

import { FormatEditor } from './version-formats/FormatEditor'
import { FormatList } from './version-formats/FormatList'
import { VersionTester } from './version-formats/VersionTester'

// Keyed by the selected org's slug at the Admin call site, so it remounts (and
// re-seeds from the new org's formats) whenever the active organization
// changes — no resync effect needed.
// fallow-ignore-next-line complexity
export function DefaultSettingsManagement() {
  const { selectedOrganization } = useOrganization()
  const queryClient = useQueryClient()
  const orgSlug = selectedOrganization?.slug
  const baseFormats = orgTagFormats(selectedOrganization)

  const [rows, setRows] = useState<FormatRow[]>(() => buildRows(baseFormats))
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<FormatRow | null>(null)
  // Normalize through buildRows/toFormats so the baseline matches the editor's
  // canonical ordering (built-ins first); otherwise a differently-ordered
  // baseFormats reads as dirty on mount.
  const baseline = useRef(JSON.stringify(toFormats(buildRows(baseFormats))))

  const mutation = useMutation({
    mutationFn: (operations: PatchOperation[]) =>
      updateOrganization(orgSlug ?? '', operations),
    onSuccess: () => {
      baseline.current = JSON.stringify(toFormats(rows))
      return queryClient.invalidateQueries({ queryKey: ['organizations'] })
    },
  })

  if (!orgSlug) {
    return (
      <div className="text-tertiary py-12 text-center">
        Select an organization to manage default settings.
      </div>
    )
  }

  const formats = toFormats(rows)
  const dirty = JSON.stringify(formats) !== baseline.current

  const toggleRow = (id: string) =>
    setRows((rs) =>
      rs.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)),
    )
  const removeRow = (id: string) =>
    setRows((rs) => rs.filter((r) => r.id !== id))
  const closeEditor = () => {
    setEditing(null)
    setEditorOpen(false)
  }
  const saveFormat = (label: string, pattern: string, example: string) => {
    setRows((rs) =>
      editing
        ? rs.map((r) =>
            r.id === editing.id ? { ...r, example, label, pattern } : r,
          )
        : [
            ...rs,
            {
              builtin: false,
              description: 'Custom version format.',
              enabled: true,
              example,
              id: nextRowId(),
              label,
              pattern,
            },
          ],
    )
    closeEditor()
  }
  const handleSave = () => {
    const operations = buildDiffPatch(
      { tag_formats: baseFormats },
      { tag_formats: formats },
      { fields: ['tag_formats'] },
    )
    if (operations.length > 0) mutation.mutate(operations)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-primary text-base font-medium">
            Supported version formats
          </h2>
          <p className="text-secondary mt-1 max-w-xl text-sm">
            Releases are validated against these patterns. They can be
            overridden for specific project types.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            disabled={mutation.isPending}
            onClick={() => {
              setEditing(null)
              setEditorOpen(true)
            }}
            variant="outline"
          >
            <Plus className="mr-2 size-4" />
            Add custom format
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={!dirty || mutation.isPending}
            onClick={handleSave}
          >
            <Save className="mr-2 size-4" />
            {mutation.isPending ? 'Saving...' : 'Save changes'}
          </Button>
        </div>
      </div>

      <SaveStatus
        isError={mutation.isError}
        saved={!dirty && mutation.isSuccess}
      />

      {editorOpen && (
        <FormatEditor
          initialExample={editing?.example}
          initialName={editing?.label}
          initialPattern={editing?.pattern}
          key={editing?.id ?? 'new'}
          onCancel={closeEditor}
          onSave={saveFormat}
          title={editing ? 'Edit custom format' : 'Add custom format'}
        />
      )}

      <FormatList
        disabled={mutation.isPending}
        onDelete={removeRow}
        onEdit={(row) => {
          setEditing(row)
          setEditorOpen(true)
        }}
        onToggle={toggleRow}
        rows={rows}
      />

      <VersionTester formats={formats} />
    </div>
  )
}

function orgTagFormats(org: unknown): TagFormat[] {
  return (org as null | { tag_formats?: TagFormat[] })?.tag_formats ?? []
}

function SaveStatus({ isError, saved }: { isError: boolean; saved: boolean }) {
  if (isError) {
    return (
      <Alert variant="danger">Failed to save default version formats.</Alert>
    )
  }
  if (saved) {
    return (
      <p className="text-success text-sm">Default version formats saved.</p>
    )
  }
  return null
}
