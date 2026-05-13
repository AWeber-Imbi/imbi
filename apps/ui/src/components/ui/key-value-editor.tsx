// Form-embedded key/value editor: free-form keys (user types them), controlled
// via value/onChange, no per-row save. Use inside a form that submits the
// whole object at once (see ThirdPartyServiceForm's links/identifiers state).
//
// For inline-edit on a detail page where each row is independently committed
// against the server (with confirm dialog + saved indicator + Select from a
// pre-known key set), use EditableKeyValueMap (./EditableKeyValueMap) instead.
import { useState } from 'react'

import { Plus, Trash2 } from 'lucide-react'

import { Button } from './button'
import { Input } from './input'

interface KeyValueEditorProps {
  disabled?: boolean
  keyPlaceholder?: string
  onChange: (value: Record<string, number | string>) => void
  value: Record<string, number | string>
  valuePlaceholder?: string
}

export function KeyValueEditor({
  disabled = false,
  keyPlaceholder = 'Key',
  onChange,
  value,
  valuePlaceholder = 'Value',
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
        <div className="flex items-center gap-2" key={k}>
          <Input className="flex-1 opacity-70" disabled value={k} />
          <Input className="flex-1 opacity-70" disabled value={String(v)} />
          <Button
            aria-label={`Remove ${k}`}
            className="text-danger hover:bg-danger"
            disabled={disabled}
            onClick={() => handleRemove(k)}
            size="sm"
            type="button"
            variant="ghost"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}

      <div className="flex items-center gap-2">
        <Input
          className="flex-1"
          disabled={disabled}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={keyPlaceholder}
          value={newKey}
        />
        <Input
          className="flex-1"
          disabled={disabled}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={valuePlaceholder}
          value={newValue}
        />
        <Button
          aria-label="Add key value pair"
          className="text-info hover:text-info/80"
          disabled={disabled || !newKey.trim() || !newValue.trim()}
          onClick={handleAdd}
          size="sm"
          type="button"
          variant="ghost"
        >
          <Plus className="size-4" />
        </Button>
      </div>
    </div>
  )
}
