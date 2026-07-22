import { Lock, Pencil, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// Write-only secret field. The API never returns the value, only a
// `present` boolean. Three states:
//   - present & not editing  → "•••• Set" with Replace / Clear
//   - not present & not editing → "Not set" with Set value
//   - editing → password input with Cancel
//
// `value` is the in-progress plaintext (parent owns it); `cleared` records
// that the user explicitly removed an existing secret.
interface SecretFieldProps {
  cleared: boolean
  editing: boolean
  onCancel: () => void
  onChange: (value: string) => void
  onClear: () => void
  onStart: () => void
  placeholder?: string
  present: boolean
  value: string
}

export function SecretField({
  cleared,
  editing,
  onCancel,
  onChange,
  onClear,
  onStart,
  placeholder = 'Paste new secret…',
  present,
  value,
}: SecretFieldProps) {
  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <Input
          autoComplete="new-password"
          autoFocus
          className="font-mono"
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          type="password"
          value={value}
        />
        <Button
          aria-label="Cancel"
          onClick={onCancel}
          size="sm"
          type="button"
          variant="ghost"
        >
          <X className="size-4" />
        </Button>
      </div>
    )
  }

  const hasStored = present && !cleared
  return (
    <div className="border-input bg-secondary flex items-center justify-between rounded-md border px-3 py-2">
      <span className="text-secondary inline-flex items-center gap-2 text-sm">
        {hasStored ? (
          <>
            <Lock className="text-success size-3.5" />
            <span className="text-primary font-mono tracking-widest">
              ••••••••
            </span>
            <span className="text-tertiary">Set</span>
          </>
        ) : (
          <span className="text-tertiary italic">Not set</span>
        )}
      </span>
      <div className="flex items-center gap-1">
        <Button onClick={onStart} size="sm" type="button" variant="outline">
          <Pencil className="mr-1.5 size-3.5" />
          {hasStored ? 'Replace' : 'Set value'}
        </Button>
        {hasStored && (
          <Button
            aria-label="Clear"
            className="text-destructive hover:bg-destructive/10"
            onClick={onClear}
            size="sm"
            type="button"
            variant="ghost"
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
