import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from './button'
import { Input } from './input'

interface KeyValueEditorProps {
  value: Record<string, string | number>
  onChange: (value: Record<string, string | number>) => void
  keyPlaceholder?: string
  valuePlaceholder?: string
  disabled?: boolean
}

export function KeyValueEditor({
  value,
  onChange,
  keyPlaceholder = 'Key',
  valuePlaceholder = 'Value',
  disabled = false,
}: KeyValueEditorProps) {
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  const entries = Object.entries(value)

  const handleAdd = () => {
    const trimmedKey = newKey.trim()
    const trimmedValue = newValue.trim()
    if (!trimmedKey || !trimmedValue) return
    onChange({ ...value, [trimmedKey]: trimmedValue })
    setNewKey('')
    setNewValue('')
  }

  const handleRemove = (key: string) => {
    const next = { ...value }
    delete next[key]
    onChange(next)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAdd()
    }
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <Input value={k} disabled className="flex-1 opacity-70" />
          <Input value={String(v)} disabled className="flex-1 opacity-70" />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Remove ${k}`}
            onClick={() => handleRemove(k)}
            disabled={disabled}
            className="text-danger hover:bg-danger"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}

      <div className="flex items-center gap-2">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={keyPlaceholder}
          disabled={disabled}
          className="flex-1"
        />
        <Input
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={valuePlaceholder}
          disabled={disabled}
          className="flex-1"
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="Add key value pair"
          onClick={handleAdd}
          disabled={disabled || !newKey.trim() || !newValue.trim()}
          className="hover:text-info/80 text-info"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
