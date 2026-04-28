import { useMemo } from 'react'

import { EditableKeyValueMap } from '@/components/ui/EditableKeyValueMap'
import { useEditableKeyValueMap } from '@/hooks/useEditableKeyValueMap'

interface EditIdentifiersCardProps {
  identifiers: Record<string, number | string>
  onPatch: (identifiers: Record<string, string>) => Promise<void>
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
    normalizeValue: (v) => v.trim(),
    onPatch,
    serverMap,
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
      deleteDialogDescription="This will clear the identifier value on the project."
      getDeleteDialogTitle={(key) =>
        key ? `Remove ${toLabel(key)} identifier?` : 'Remove identifier?'
      }
      getNewValuePlaceholder={(newKey) =>
        newKey ? toLabel(newKey) : 'identifier'
      }
      getRemoveAriaLabel={(key) => `Remove ${toLabel(key)} identifier`}
      getValuePlaceholder={(key) => toLabel(key)}
      hideWhenEmpty
      newKeyPlaceholder="Pick Identifier to Add"
      renderKeyLabel={(key) => (
        <div className="w-[15%] flex-shrink-0 truncate text-sm text-secondary">
          {toLabel(key)}
        </div>
      )}
      renderSelectItem={(key) => toLabel(key)}
      renderSelectTrigger={(newKey) => (
        <div className="flex min-w-0 items-center text-secondary">
          <span className="truncate">{toLabel(newKey)}</span>
        </div>
      )}
      state={state}
      title="Identifiers"
      unassignedKeys={unassignedKeys}
      valueInputClassName="font-mono text-sm"
      visibleKeys={visibleKeys}
    />
  )
}

function toLabel(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
