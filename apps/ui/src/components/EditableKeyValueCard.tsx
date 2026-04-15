import { useState, useEffect } from 'react'
import { Trash2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'

interface EditableKeyValueCardProps {
  title: string
  entries: Record<string, string | number>
  isDarkMode: boolean
  isSaving: boolean
  keyLabel?: string
  valueLabel?: string
  keyPlaceholder?: string
  valuePlaceholder?: string
  readOnlyKeys?: boolean
  showHeader?: boolean
  onSave: (entries: Record<string, string>) => void
}

export function EditableKeyValueCard({
  title,
  entries,
  isDarkMode,
  isSaving,
  keyLabel = 'Key',
  valueLabel = 'Value',
  keyPlaceholder = 'key',
  valuePlaceholder = 'value',
  readOnlyKeys = false,
  showHeader = true,
  onSave,
}: EditableKeyValueCardProps) {
  const [rows, setRows] = useState<[string, string][]>([])

  useEffect(() => {
    setRows(
      Object.entries(entries)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => [k, String(v)]),
    )
  }, [entries])

  const updateRow = (index: number, col: 0 | 1, value: string) => {
    setRows((prev) => {
      const next = [...prev]
      next[index] = [...next[index]] as [string, string]
      next[index][col] = value
      return next
    })
  }

  const removeRow = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index))
  }

  const addRow = () => {
    setRows((prev) => [...prev, ['', '']])
  }

  const handleSave = () => {
    const result: Record<string, string> = {}
    for (const [k, v] of rows) {
      const key = k.trim()
      if (key) result[key] = v
    }
    onSave(result)
  }

  const inputClass = isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
  const headerClass = `mb-4 ${isDarkMode ? 'text-white' : 'text-slate-900'}`
  const labelClass = `text-xs font-medium ${isDarkMode ? 'text-gray-400' : 'text-slate-500'}`

  return (
    <Card className={`p-6 ${isDarkMode ? 'border-gray-700 bg-gray-800' : ''}`}>
      <h3 className={headerClass}>{title}</h3>

      {showHeader && rows.length > 0 && (
        <div className="mb-2 flex items-center gap-2 px-1">
          <span className={`flex-1 ${labelClass}`}>{keyLabel}</span>
          <span className={`flex-1 ${labelClass}`}>{valueLabel}</span>
          <div className="w-8" />
        </div>
      )}

      <div className="space-y-2">
        {rows.map(([key, val], index) => (
          <div key={`${index}-${key}`} className="flex items-center gap-2">
            {readOnlyKeys ? (
              <span
                className={`w-[15%] flex-shrink-0 text-sm ${isDarkMode ? 'text-gray-300' : 'text-slate-700'}`}
              >
                {key}
              </span>
            ) : (
              <Input
                value={key}
                onChange={(e) => updateRow(index, 0, e.target.value)}
                disabled={isSaving}
                placeholder={keyPlaceholder}
                className={`flex-1 font-mono text-sm ${inputClass}`}
              />
            )}
            <Input
              value={val}
              onChange={(e) => updateRow(index, 1, e.target.value)}
              disabled={isSaving}
              placeholder={valuePlaceholder}
              className={`flex-1 text-sm ${inputClass}`}
            />
            <button
              type="button"
              aria-label={`Remove ${title.toLowerCase()} row ${index + 1}`}
              onClick={() => removeRow(index)}
              disabled={isSaving}
              className={`rounded p-1.5 ${
                isDarkMode
                  ? 'text-red-400 hover:bg-red-900/20'
                  : 'text-red-600 hover:bg-red-50'
              }`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between">
        {!readOnlyKeys ? (
          <Button
            variant="outline"
            size="sm"
            onClick={addRow}
            disabled={isSaving}
            className={
              isDarkMode
                ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                : ''
            }
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Add
          </Button>
        ) : (
          <div />
        )}
        <Button
          size="sm"
          className="border-amber-border bg-amber-bg text-amber-text hover:bg-amber-bg/80"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
