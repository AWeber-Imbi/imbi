import { useMemo } from 'react'
import { EditableKeyValueMap } from '@/components/ui/EditableKeyValueMap'
import { useEditableKeyValueMap } from '@/hooks/useEditableKeyValueMap'

interface EditIdentifiersCardProps {
  identifiers: Record<string, string | number>
  onPatch: (identifiers: Record<string, string>) => Promise<void>
}

function toLabel(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function EditIdentifiersCard({
  identifiers,
  onPatch,
}: EditIdentifiersCardProps) {
  const serverMap = useMemo<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(identifiers)) {
      out[k] = v == null ? '' : String(v)
    }
    return out
  }, [identifiers])

  const state = useEditableKeyValueMap<string>({
    serverMap,
    onPatch,
    normalizeValue: (v) => v.trim(),
  })

  const visibleKeys = useMemo(
    () =>
      Object.keys(serverMap)
        .filter((k) => (serverMap[k] ?? '').trim() !== '')
        .sort((a, b) => a.localeCompare(b)),
    [serverMap],
  )

  const unassignedKeys = useMemo(
    () =>
      Object.keys(serverMap)
        .filter((k) => (serverMap[k] ?? '').trim() === '')
        .sort((a, b) => a.localeCompare(b)),
    [serverMap],
  )

  return (
    <EditableKeyValueMap
      state={state}
      title="Identifiers"
      visibleKeys={visibleKeys}
      unassignedKeys={unassignedKeys}
      valueInputClassName="font-mono text-sm"
      renderKeyLabel={(key) => (
        <div className="w-[15%] flex-shrink-0 truncate text-sm text-secondary">
          {toLabel(key)}
        </div>
      )}
      renderSelectTrigger={(newKey) => (
        <div className="flex min-w-0 items-center text-secondary">
          <span className="truncate">{toLabel(newKey)}</span>
        </div>
      )}
      renderSelectItem={(key) => toLabel(key)}
      getValuePlaceholder={(key) => toLabel(key)}
      getNewValuePlaceholder={(newKey) =>
        newKey ? toLabel(newKey) : 'identifier'
      }
      newKeyPlaceholder="Pick Identifier to Add"
      getRemoveAriaLabel={(key) => `Remove ${toLabel(key)} identifier`}
      getDeleteDialogTitle={(key) =>
        key ? `Remove ${toLabel(key)} identifier?` : 'Remove identifier?'
      }
      deleteDialogDescription="This will clear the identifier value on the project."
      hideWhenEmpty
    />
  )
}
