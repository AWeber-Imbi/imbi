import { useEffect, useState } from 'react'

import { Textarea } from '@/components/ui/textarea'

export type EnvPayloads = Record<string, Record<string, unknown>>

interface EnvPayloadsEditorProps {
  disabled?: boolean
  id: string
  label: string
  onChange: (next: EnvPayloads) => void
  value: EnvPayloads
}

// Per-environment payloads of a capability assignment, edited as one JSON
// object keyed by environment slug. A valid, changed value is committed on
// blur; an invalid value shows an error and is not committed.
export function EnvPayloadsEditor({
  disabled = false,
  id,
  label,
  onChange,
  value,
}: EnvPayloadsEditorProps) {
  const formatted = formatEnvPayloads(value)
  const [text, setText] = useState(formatted)
  const [error, setError] = useState<null | string>(null)

  useEffect(() => {
    setText(formatted)
    setError(null)
  }, [formatted])

  const commit = () => {
    try {
      const next = parseEnvPayloads(text)
      setError(null)
      if (formatEnvPayloads(next) !== formatted) onChange(next)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-1">
      <Textarea
        aria-invalid={!!error}
        aria-label={label}
        className="min-h-24 font-mono text-xs"
        disabled={disabled}
        id={id}
        onBlur={commit}
        onChange={(e) => setText(e.target.value)}
        placeholder={'{\n  "production": { "region": "us-east-1" }\n}'}
        value={text}
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

export function formatEnvPayloads(value: EnvPayloads): string {
  return Object.keys(value).length === 0 ? '' : JSON.stringify(value, null, 2)
}

// Parse the editor text. Blank text means no payloads. Throws an Error with
// a message for the user when the text is not an object of objects.
export function parseEnvPayloads(text: string): EnvPayloads {
  if (!text.trim()) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('Enter valid JSON.')
  }
  if (!isObject(parsed)) {
    throw new Error('Enter a JSON object keyed by environment slug.')
  }
  for (const [env, payload] of Object.entries(parsed)) {
    if (!isObject(payload)) {
      throw new Error(`The payload for "${env}" must be a JSON object.`)
    }
  }
  return parsed as EnvPayloads
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
