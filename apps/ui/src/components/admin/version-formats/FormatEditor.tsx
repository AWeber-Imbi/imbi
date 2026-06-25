import { useState } from 'react'

import { AlertTriangle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fullMatch, isValidPattern } from '@/lib/versionFormats'

interface FormatEditorProps {
  initialExample?: string
  initialName?: string
  initialPattern?: string
  onCancel: () => void
  onSave: (label: string, pattern: string, example: string) => void
  title: string
}

// fallow-ignore-next-line complexity
export function FormatEditor({
  initialExample = '',
  initialName = '',
  initialPattern = '',
  onCancel,
  onSave,
  title,
}: FormatEditorProps) {
  const [name, setName] = useState(initialName)
  const [pattern, setPattern] = useState(initialPattern)
  const [test, setTest] = useState(initialExample)

  const patternValid = !pattern || isValidPattern(pattern)
  const canSave = !!name.trim() && !!pattern.trim() && patternValid
  const matched =
    !!test && !!pattern && patternValid && fullMatch(pattern, test)
  const noMatch = !!test && !!pattern && patternValid && !matched

  return (
    <div className="border-input rounded-lg border p-4">
      <div className="text-tertiary mb-3 text-xs font-semibold tracking-wide uppercase">
        {title}
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1.5fr]">
        <div>
          <Label className="text-secondary mb-1.5 block text-xs">Name</Label>
          <Input
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Build number"
            value={name}
          />
        </div>
        <div>
          <Label className="text-secondary mb-1.5 block text-xs">
            Pattern · regular expression
          </Label>
          <Input
            className="font-mono text-xs"
            onChange={(e) => setPattern(e.target.value)}
            placeholder="^build-\d+$"
            value={pattern}
          />
          {!patternValid && (
            <div className="text-danger mt-1.5 flex items-center gap-1 text-xs">
              <AlertTriangle className="size-3" />
              Not a valid regular expression.
            </div>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-tertiary text-xs">Try it</span>
        <Input
          className="max-w-65 font-mono text-xs"
          onChange={(e) => setTest(e.target.value)}
          placeholder="Test a version"
          value={test}
        />
        {matched && <Badge variant="success">Match</Badge>}
        {noMatch && <Badge variant="danger">No match</Badge>}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onCancel} size="sm" variant="ghost">
          Cancel
        </Button>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover"
          disabled={!canSave}
          onClick={() => onSave(name.trim(), pattern.trim(), test.trim())}
          size="sm"
        >
          Save format
        </Button>
      </div>
    </div>
  )
}
