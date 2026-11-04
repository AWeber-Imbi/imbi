import { useState } from 'react'

import { AlertTriangle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { schemeError, schemePattern } from '@/lib/calverSchemes'
import { fullMatch, isValidPattern } from '@/lib/versionFormats'

interface FormatEditorProps {
  initialExample?: string
  initialName?: string
  initialPattern?: string
  initialScheme?: string
  onCancel: () => void
  onSave: (
    label: string,
    pattern: string,
    example: string,
    scheme: null | string,
  ) => void
  title: string
}

// fallow-ignore-next-line complexity
export function FormatEditor({
  initialExample = '',
  initialName = '',
  initialPattern = '',
  initialScheme = '',
  onCancel,
  onSave,
  title,
}: FormatEditorProps) {
  const [name, setName] = useState(initialName)
  const [regex, setRegex] = useState(initialPattern)
  const [scheme, setScheme] = useState(initialScheme)
  const [test, setTest] = useState(initialExample)

  // A calendar scheme, when given, sets the pattern.
  const trimmedScheme = scheme.trim()
  const schemeProblem = trimmedScheme ? schemeError(trimmedScheme) : null
  const pattern =
    trimmedScheme && !schemeProblem ? schemePattern(trimmedScheme) : regex
  const patternValid = !pattern || isValidPattern(pattern)
  const canSave =
    !!name.trim() && !!pattern.trim() && patternValid && !schemeProblem
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
            Calendar scheme · optional, calver.org notation
          </Label>
          <Input
            aria-label="Calendar scheme"
            className="font-mono text-xs"
            onChange={(e) => setScheme(e.target.value)}
            placeholder="YY.0M.MICRO"
            value={scheme}
          />
          {schemeProblem ? (
            <div className="text-danger mt-1.5 flex items-center gap-1 text-xs">
              <AlertTriangle className="size-3" />
              {schemeProblem}
            </div>
          ) : (
            <div className="text-tertiary mt-1.5 text-xs">
              Sets the pattern and the next suggested tag.
            </div>
          )}
        </div>
        <div className="md:col-start-2">
          <Label className="text-secondary mb-1.5 block text-xs">
            Pattern · regular expression
          </Label>
          <Input
            aria-label="Pattern"
            className="font-mono text-xs"
            disabled={!!trimmedScheme}
            onChange={(e) => setRegex(e.target.value)}
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
          onClick={() =>
            onSave(
              name.trim(),
              pattern.trim(),
              test.trim(),
              trimmedScheme || null,
            )
          }
          size="sm"
        >
          Save format
        </Button>
      </div>
    </div>
  )
}
