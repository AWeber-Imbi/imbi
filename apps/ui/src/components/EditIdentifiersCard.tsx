import { useEffect, useMemo, useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { SavedIndicator } from '@/components/ui/saved-indicator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSavedFlash } from '@/hooks/useSavedFlash'

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

function normalize(
  identifiers: Record<string, string | number>,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(identifiers)) {
    out[k] = v == null ? '' : String(v)
  }
  return out
}

export function EditIdentifiersCard({
  identifiers,
  onPatch,
}: EditIdentifiersCardProps) {
  const serverMap = useMemo(() => normalize(identifiers), [identifiers])
  const [drafts, setDrafts] = useState<Record<string, string>>(serverMap)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [newKey, setNewKey] = useState<string | null>(null)
  const [newValue, setNewValue] = useState('')
  const [selectKey, setSelectKey] = useState(0)
  const newValueRef = useRef<HTMLInputElement>(null)
  const shouldFocusNewValue = useRef(false)
  const { saved, flash } = useSavedFlash()

  useEffect(() => {
    setDrafts(serverMap)
  }, [serverMap])

  useEffect(() => {
    if (shouldFocusNewValue.current) {
      newValueRef.current?.focus()
      shouldFocusNewValue.current = false
    }
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

  const handleBlur = async (key: string) => {
    const next = (drafts[key] ?? '').trim()
    const current = serverMap[key] ?? ''
    if (next === current) return
    if (!next && current) {
      setPendingDelete(key)
      return
    }
    // Merge the latest drafts so a blur that races with an in-flight PATCH
    // does not revive stale server values for concurrently-edited fields.
    const payload: Record<string, string> = {
      ...serverMap,
      ...drafts,
      [key]: next,
    }
    try {
      await onPatch(payload)
      flash(key)
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }

  const requestDelete = (key: string) => {
    if (!(serverMap[key] ?? '').trim()) return
    setPendingDelete(key)
  }

  const cancelDelete = () => {
    const key = pendingDelete
    if (key && serverMap[key]) {
      setDrafts((prev) => ({ ...prev, [key]: serverMap[key] }))
    }
    setPendingDelete(null)
  }

  const confirmDelete = async () => {
    const key = pendingDelete
    if (!key) return
    const payload: Record<string, string> = {}
    for (const [k, v] of Object.entries(serverMap)) {
      if (k === key) continue
      const t = (v ?? '').trim()
      if (t) payload[k] = t
    }
    try {
      await onPatch(payload)
      setDrafts((prev) => {
        const { [key]: _, ...rest } = prev
        return rest
      })
    } catch {
      // Parent surfaces the error.
    } finally {
      setPendingDelete(null)
    }
  }

  const handleNewKeyChange = (key: string) => {
    if (!key) return
    setNewKey(key)
    shouldFocusNewValue.current = true
  }

  const handleNewBlur = async () => {
    const value = newValue.trim()
    if (!newKey || !value) return
    // Include the latest drafts so concurrent edits to existing identifiers
    // aren't reverted to stale server values by this add.
    const payload: Record<string, string> = {
      ...serverMap,
      ...drafts,
      [newKey]: value,
    }
    try {
      await onPatch(payload)
      flash(newKey)
      setNewKey(null)
      setNewValue('')
      setSelectKey((k) => k + 1)
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }

  if (visibleKeys.length === 0 && unassignedKeys.length === 0) return null

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">Identifiers</h3>

      <div className="space-y-3">
        {visibleKeys.map((key) => (
          <div key={key} className="flex items-center gap-3">
            <div className="w-[15%] flex-shrink-0 truncate text-sm text-secondary">
              {toLabel(key)}
            </div>
            <div className="relative flex-1">
              <Input
                value={drafts[key] ?? ''}
                onChange={(e) =>
                  setDrafts((prev) => ({ ...prev, [key]: e.target.value }))
                }
                onBlur={() => handleBlur(key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    e.currentTarget.blur()
                  }
                }}
                placeholder={toLabel(key)}
                className="pr-8 font-mono text-sm"
              />
              <SavedIndicator show={!!saved[key]} />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ${toLabel(key)} identifier`}
              className="h-8 w-8 flex-shrink-0 text-secondary hover:text-danger"
              onClick={() => requestDelete(key)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}

        {unassignedKeys.length > 0 && (
          <div className="flex items-center gap-3 pt-2">
            <Select
              key={selectKey}
              value={newKey ?? ''}
              onValueChange={handleNewKeyChange}
            >
              <SelectTrigger className="w-[15%] flex-shrink-0 text-sm">
                {newKey ? (
                  <div className="flex min-w-0 items-center text-secondary">
                    <span className="truncate">{toLabel(newKey)}</span>
                  </div>
                ) : (
                  <SelectValue placeholder="Pick Identifier to Add" />
                )}
              </SelectTrigger>
              <SelectContent>
                {unassignedKeys.map((key) => (
                  <SelectItem key={key} value={key}>
                    {toLabel(key)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              ref={newValueRef}
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              onBlur={handleNewBlur}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  e.currentTarget.blur()
                }
              }}
              placeholder={newKey ? toLabel(newKey) : 'identifier'}
              disabled={!newKey}
              className="flex-1 font-mono text-sm"
            />
            <div className="h-8 w-8 flex-shrink-0" aria-hidden />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={
          pendingDelete
            ? `Remove ${toLabel(pendingDelete)} identifier?`
            : 'Remove identifier?'
        }
        description="This will clear the identifier value on the project."
        confirmLabel="Remove"
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />
    </Card>
  )
}
