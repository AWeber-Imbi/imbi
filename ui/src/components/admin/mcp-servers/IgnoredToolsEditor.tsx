import { useState } from 'react'

import { Plus, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Free-form list of tool names to hide from the assistant. Maps directly to
// the server's `ignored_tools` array. An ignored tool is never registered, so
// its namespaced name (mcp_{prefix}_{tool}) won't reach the model.
//
// When a connection test has discovered the server's live tools, they're
// offered in a dropdown; names can also be typed directly (e.g. before a
// test, or for a tool that blocks a clean test).
interface IgnoredToolsEditorProps {
  // Live tool names discovered by the last connection test, if any.
  availableTools?: string[]
  onChange: (value: string[]) => void
  value: string[]
}

export function IgnoredToolsEditor({
  availableTools = [],
  onChange,
  value,
}: IgnoredToolsEditorProps) {
  const [draft, setDraft] = useState('')

  const add = (name: string) => {
    const trimmed = name.trim()
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed])
    }
  }

  const remove = (name: string) => {
    onChange(value.filter((t) => t !== name))
  }

  const selectable = availableTools.filter((t) => !value.includes(t))

  return (
    <div className="space-y-3">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((name) => (
            <span
              className="bg-secondary text-primary inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-xs"
              key={name}
            >
              {name}
              <button
                aria-label={`Remove ${name}`}
                className="text-tertiary hover:text-destructive"
                onClick={() => remove(name)}
                type="button"
              >
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      {selectable.length > 0 && (
        <Select onValueChange={(v) => add(v)} value="">
          <SelectTrigger aria-label="Ignore a discovered tool">
            <SelectValue placeholder="Ignore a discovered tool…" />
          </SelectTrigger>
          <SelectContent>
            {selectable.map((name) => (
              <SelectItem className="font-mono" key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <div className="flex items-center gap-2">
        <Input
          className="font-mono"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add(draft)
              setDraft('')
            }
          }}
          placeholder={
            availableTools.length > 0
              ? 'or add a tool name…'
              : 'tool_name to ignore…'
          }
          value={draft}
        />
        <Button
          disabled={!draft.trim()}
          onClick={() => {
            add(draft)
            setDraft('')
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <Plus className="mr-1.5 size-3.5" />
          Add
        </Button>
      </div>

      {availableTools.length === 0 && (
        <p className="text-tertiary text-xs">
          Run a connection test to list this server&apos;s tools and pick them
          from a dropdown.
        </p>
      )}
    </div>
  )
}
